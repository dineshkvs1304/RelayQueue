
from sqlalchemy import text

from relayqueue.database.connection import engine


def main() -> None:
    try:
        with engine.connect() as connection:
            result = connection.execute(
                text("SELECT current_database(), version()")
            ).one()

            print("Database connection successful!")
            print(f"Database: {result[0]}")
            print(f"Server: {result[1]}")

    except Exception as error:
        print(f"Database connection failed: {error}")
        raise


if __name__ == "__main__":
    main()
