"""UTC day labels for persisted KPI windows, independent of DB session timezone."""
from sqlalchemy import Date, cast, func, literal_column
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement


class utc_report_day(FunctionElement):
    type = Date()
    inherit_cache = True


@compiles(utc_report_day)
def _sqlite_day(element, compiler, **kwargs):
    return compiler.process(func.date(*element.clauses), **kwargs)


@compiles(utc_report_day, "postgresql")
def _postgres_day(element, compiler, **kwargs):
    timestamp = list(element.clauses)[0]
    return compiler.process(cast(func.timezone(literal_column("'UTC'"), timestamp), Date), **kwargs)
