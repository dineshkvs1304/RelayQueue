
import psycopg
from psycopg.errors import DuplicateDatabase

from relayqueue.core.config import get_settings


def main() -> None:
    settings = get_settings()

    connection = psycopg.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        dbname="postgres",
        autocommit=True,
    )

    try:
        with connection.cursor() as cursor:
            try:
                cursor.execute(
                    'CREATE DATABASE "relayqueue_test"'
                )
                print("SUCCESS: relayqueue_test database created.")

            except DuplicateDatabase:
                print("INFO: relayqueue_test already exists.")

    finally:
        connection.close()


if __name__ == "__main__":
    main()
