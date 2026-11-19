import uvicorn

from .main import HOST, PORT, app
from .storage_migration import migrate_storage


def main():
    migrate_storage()
    uvicorn.run(
        app,
        host=HOST,
        port=PORT,
        reload=False,
        log_config=None,
        access_log=False,
    )


if __name__ == "__main__":
    main()
