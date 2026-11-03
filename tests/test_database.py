from sqlalchemy import text


def test_database_connection(db_session):
    result = db_session.execute(text("SELECT current_database()")).scalar_one()

    assert result == "relayqueue_test"


def test_database_tables_exist(db_session):
    result = db_session.execute(
        text(
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_type = 'BASE TABLE'
            """
        )
    ).scalar_one()

    assert result >= 3
