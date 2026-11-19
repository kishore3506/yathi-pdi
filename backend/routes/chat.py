import logging
import json
from datetime import datetime
from typing import List, Literal

from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field, validator
from pypdf.errors import PdfReadError

try:
    from ..database import get_db
    from ..services.chat_context import build_chat_context
    from ..services.gemini_service import GeminiService
    from ..services.report_analysis import (
        MAX_REPORT_FILE_BYTES,
        MAX_REPORT_TEXT_CHARS,
        extract_report_text,
        render_report_analysis,
        select_existing_reports,
    )
    from ..services.report_summary import build_daily_comparison_summary, render_daily_comparison_pdf
except (ImportError, ValueError):
    from database import get_db
    from services.chat_context import build_chat_context
    from services.gemini_service import GeminiService
    from services.report_analysis import (
        MAX_REPORT_FILE_BYTES,
        MAX_REPORT_TEXT_CHARS,
        extract_report_text,
        render_report_analysis,
        select_existing_reports,
    )
    from services.report_summary import build_daily_comparison_summary, render_daily_comparison_pdf

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=3000)


class ChatRequest(BaseModel):
    messages: List[ChatMessage] = Field(..., min_items=1, max_items=12)

    @validator("messages")
    def conversation_ends_with_user_message(cls, messages):
        if messages[-1].role != "user":
            raise ValueError("The last chat message must be from the user.")
        return messages


class ChatResponse(BaseModel):
    answer: str


class AppQuestion(ChatRequest):
    screen: Literal["dashboard", "new-inspection", "generated-reports", "job-review", "report-editor", "templates", "employees", "backups"] | None = None
    job_id: int | None = Field(default=None, ge=1)
    report_id: int | None = Field(default=None, ge=1)


class ReportAnalysisRequest(BaseModel):
    request_text: str = Field(..., min_length=1, max_length=3000)
    output_format: Literal["pdf", "docx", "both"] = "pdf"


def _analysis_download(analysis: str, source_name: str, output_format: str) -> Response:
    try:
        content, media_type, extension = render_report_analysis(
            analysis,
            source_name,
            output_format,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    filename = f"pdi_report_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}{extension}"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _generate_report_analysis(source_name: str, report_text: str) -> str:
    assistant = GeminiService()
    if not assistant.api_key:
        raise HTTPException(
            status_code=503,
            detail="AI report analysis is unavailable because GEMINI_API_KEY is not configured.",
        )

    try:
        return assistant.generate_chat_response(
            [{
                "role": "user",
                "content": (
                    f"Analyze this PDI report from {source_name}. Provide a concise executive summary, "
                    "report identity, overall inspection outcome if explicitly stated, missing or "
                    "inconsistent details, observations that conflict with stated specifications, "
                    "and items requiring human review. Do not infer unstated requirements.\n\n"
                    f"Report content:\n{report_text}"
                ),
            }],
            report_analysis=True,
        )
    except TimeoutError as exc:
        logger.warning("Gemini report analysis timed out: %s", exc)
        raise HTTPException(
            status_code=504,
            detail="The AI report analysis took too long. Please try again.",
        ) from exc
    except (RuntimeError, ValueError) as exc:
        logger.exception("Gemini report analysis failed")
        raise HTTPException(
            status_code=502,
            detail="The AI could not analyze this report. Please try again.",
        ) from exc


@router.post("", response_model=ChatResponse)
def chat(request: AppQuestion, http_request: Request):
    assistant = GeminiService()
    if not assistant.api_key:
        raise HTTPException(
            status_code=503,
            detail="AI chat is unavailable because GEMINI_API_KEY is not configured.",
        )

    try:
        viewer = http_request.state.user
        answer = assistant.generate_chat_response(
            [message.model_dump() for message in request.messages],
            application_context=build_chat_context(
                screen=request.screen,
                role="local operator" if isinstance(viewer, dict) and viewer.get("local_access") else viewer["role"],
                job_id=request.job_id if request.screen == "job-review" else None,
                report_id=request.report_id if request.screen == "report-editor" else None,
                question="\n".join(message.content for message in request.messages if message.role == "user"),
            ),
        )
    except TimeoutError as exc:
        logger.warning("Gemini chat timed out: %s", exc)
        raise HTTPException(status_code=504, detail="The AI assistant took too long to respond. Please try again.") from exc
    except (RuntimeError, ValueError) as exc:
        logger.exception("Gemini chat request failed")
        raise HTTPException(status_code=502, detail="The AI assistant could not respond. Please try again.") from exc

    return ChatResponse(answer=answer)


@router.post("/analyze-report")
async def analyze_uploaded_report(
    file: UploadFile = File(...),
    output_format: Literal["pdf", "docx", "both"] = Form("pdf"),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Choose a report file to analyze.")

    file_content = await file.read(MAX_REPORT_FILE_BYTES + 1)
    await file.close()
    try:
        report_text = extract_report_text(file_content, file.filename)
    except (ValueError, PdfReadError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    analysis = _generate_report_analysis(file.filename, report_text)
    return _analysis_download(analysis, file.filename, output_format)


@router.post("/analyze-existing-reports")
def analyze_existing_reports(request: ReportAnalysisRequest):
    conn = get_db()
    try:
        conn.execute("PRAGMA query_only = ON")
        cursor = conn.cursor()
        cursor.execute("""
            SELECT r.id, r.report_code, r.status AS report_status, r.created_at,
                   j.company_name, j.product_type, j.model_name, j.product_number,
                   j.po_number, j.status AS job_status
            FROM generated_reports r
            JOIN report_jobs j ON j.id = r.job_id
            ORDER BY r.created_at DESC
        """)
        available_reports = [dict(row) for row in cursor.fetchall()]
        try:
            selected_reports = select_existing_reports(request.request_text, available_reports)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        report_ids = [report["id"] for report in selected_reports]
        placeholders = ",".join("?" for _ in report_ids)
        cursor.execute(
            f"SELECT id, report_data_json FROM generated_reports WHERE id IN ({placeholders})",
            report_ids,
        )
        report_data_by_id = {
            row["id"]: json.loads(row["report_data_json"])
            for row in cursor.fetchall()
        }
    except json.JSONDecodeError as exc:
        logger.exception("Stored PDI report data could not be decoded")
        raise HTTPException(status_code=500, detail="Stored report data could not be read.") from exc
    finally:
        if conn is not None:
            conn.close()

    if len(report_data_by_id) != len(selected_reports):
        raise HTTPException(status_code=500, detail="One or more selected reports could not be read.")

    report_text = "\n\n".join(
        json.dumps(
            {
                "report_metadata": report,
                "inspection_data": report_data_by_id[report["id"]],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        for report in selected_reports
    )
    if len(report_text) > MAX_REPORT_TEXT_CHARS:
        raise HTTPException(
            status_code=413,
            detail="The selected reports contain too much data to analyze together. Narrow your request.",
        )

    source_name = ", ".join(report["report_code"] for report in selected_reports)
    analysis = _generate_report_analysis(source_name, report_text)
    return _analysis_download(analysis, source_name, request.output_format)


@router.post("/parse-report-request")
def parse_report_request(request: ChatRequest):
    """Extract explicit report requirements from the user's chat messages."""
    assistant = GeminiService()
    if not assistant.api_key:
        raise HTTPException(
            status_code=503,
            detail="AI report creation is unavailable because GEMINI_API_KEY is not configured.",
        )

    user_text = "\n".join(
        message.content
        for message in request.messages
        if message.role == "user"
    )
    extracted = assistant.extract_document_info(
        text_content=f"User's PDI report requirements:\n{user_text}",
        extra_hints="Extract only values explicitly supplied by the user. Do not invent missing fields.",
    )
    if extracted.get("error"):
        logger.warning("Chat report request extraction failed: %s", extracted["error"])
        raise HTTPException(
            status_code=502,
            detail="The AI could not read the report requirements. Please retry or enter the missing details manually.",
        )

    model_items = extracted.get("model_items")
    if not isinstance(model_items, list) or not model_items:
        model_items = [{
            "model_name": extracted.get("model_name"),
            "product_number": extracted.get("product_number"),
            "lot_size": extracted.get("lot_size"),
            "po_number": extracted.get("po_number"),
        }]

    models = [{
        "model_name": str(item.get("model_name") or item.get("item_name") or "").strip(),
        "product_number": str(item.get("product_number") or "").strip(),
        "lot_size": item.get("lot_size"),
        "po_number": str(item.get("po_number") or extracted.get("po_number") or "").strip(),
    } for item in model_items if isinstance(item, dict)]
    if not models:
        models = [{"model_name": "", "product_number": "", "lot_size": None, "po_number": ""}]

    return {
        "company_name": str(extracted.get("company_name") or extracted.get("customer_name") or "").strip(),
        "product_type": str(extracted.get("product_type") or "").strip(),
        "models": models,
    }


@router.get("/reports/daily-comparison.pdf")
def download_daily_comparison_pdf():
    summary = build_daily_comparison_summary()
    pdf_content = render_daily_comparison_pdf(summary)
    filename = f"pdi_report_summary_{summary['today']}_vs_{summary['yesterday']}.pdf"
    return Response(
        content=pdf_content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
