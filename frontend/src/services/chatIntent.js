export function classifyChatIntent(content, hasAttachment) {
  if (/\?\s*$/.test(content) || /^(?:how|what|why|when|where|who|which|can|could|would|should|do|does|did|is|are|will|may)\b/i.test(content)) {
    return 'question';
  }

  const request = content.replace(/^(?:please help me to\s+|i (?:want|need) (?:you to|to)\s+|(?:please|kindly)\s+)+/i, '');
  const downloadable = /\b(?:pdf|word|docx|download(?:able)?)\b/i.test(request);
  const dailyComparison = /\b(?:today|yesterday|compare|comparison|difference)\b/i.test(request);
  const explicitlyExport = /^(?:create|generate|make|prepare|build|give me|export|download|compare)\b/i.test(request);
  const reportSubject = /\b(?:pdi|inspection|reports?)\b/i.test(request);
  if (explicitlyExport && /\b(?:pdf|download(?:able)?)\b/i.test(request)
    && dailyComparison && reportSubject && !hasAttachment) {
    return 'daily-comparison';
  }

  if (/^(?:analy[sz]e|summari[sz]e|review)\b/i.test(request)
    && !/^(?:analy[sz]e|summari[sz]e|review)\s+(?:how|why|when|whether|the steps)\b/i.test(request)
    && (hasAttachment || (downloadable && reportSubject) || /^analy[sz]e\s+(?:the\s+|all\s+|this\s+|existing\s+)*(?:pdi\s+)?reports?\b/i.test(request))) {
    return 'report-analysis';
  }

  if (/^(?:create|generate|make|prepare|build)\s+(?:(?:a|an|the|draft|new|pdi|inspection|\d+)\s+)*(?:pdi|reports?)\b/i.test(request)
    && !/\b(?:count|counts|summary|comparison|example|instructions|tutorial)\b/i.test(request)) {
    return 'report-draft';
  }
  return 'question';
}
