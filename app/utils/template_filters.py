from datetime import date, datetime, timezone


def register_filters(app):
    @app.template_filter("timesince")
    def timesince(value):
        if value is None:
            return ""
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = now - value
        seconds = delta.total_seconds()
        if seconds < 60:
            return "just now"
        minutes = seconds / 60
        if minutes < 60:
            return f"{int(minutes)} minute{'s' if minutes >= 2 else ''} ago"
        hours = minutes / 60
        if hours < 24:
            return f"{int(hours)} hour{'s' if hours >= 2 else ''} ago"
        days = hours / 24
        if days < 2:
            return "Yesterday"
        if days < 30:
            return f"{int(days)} days ago"
        return value.strftime("%m/%d/%Y")

    @app.template_filter("money")
    def money(value):
        try:
            return f"${float(value):,.2f}"
        except (TypeError, ValueError):
            return "$0.00"

    @app.template_filter("dateformat")
    def dateformat(value, fmt="%m/%d/%Y"):
        if not value:
            return "—"
        return value.strftime(fmt)
