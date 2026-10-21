import click
from sqlalchemy import inspect

from app.extensions import db


def register_cli(app):
    @app.cli.command("init-db")
    def init_db():
        """Create all database tables (existing tables are left untouched)."""
        db.create_all()
        tables = sorted(inspect(db.engine).get_table_names())
        click.echo("Tables in database: " + ", ".join(tables))

    @app.cli.command("reset-db")
    def reset_db():
        """DELETE all data and recreate the tables (development only)."""
        click.confirm("This deletes ALL data. Continue?", abort=True)
        db.drop_all()
        db.create_all()
        click.echo("Database reset.")