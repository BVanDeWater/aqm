"""Headlines visualizer for The Air Monitor.

Generates a classic broadsheet newspaper layout in HTML/CSS from NewsAPI articles.
"""

from datetime import datetime
import os

ap_months = {
    1: "Jan.", 2: "Feb.", 3: "March", 4: "April",
    5: "May", 6: "June", 7: "July", 8: "Aug.",
    9: "Sept.", 10: "Oct.", 11: "Nov.", 12: "Dec.",
}

dayint_to_day = {
    0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday",
    4: "Friday", 5: "Saturday", 6: "Sunday",
}

footer = """
    <footer class='footer'>
        <p>Made with the help of:
            <ul>
                <li><a href='https://newsapi.org/' target='_blank' rel='noopener noreferrer'>NewsAPI</a></li>
            </ul>
        </p>
    </footer>
"""


def format_date(dt, include_day_of_week=False):
    if not isinstance(dt, datetime):
        try:
            dt = datetime.strptime(dt, "%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            print(f"Could not parse datetime ({dt}): passing through.")
            return dt

    day_of_week = dayint_to_day[dt.weekday()]
    month = ap_months[dt.month]
    day = dt.day
    year = dt.year

    if include_day_of_week:
        return f"{day_of_week}, {month} {day}, {year}"
    return f"{month} {day}, {year}"


def build_article(article, is_lead=False):
    headline = article.get("title") or "Untitled"
    author = article.get("author")
    source = article.get("source", {}).get("name", "Unknown Source")
    link = article.get("url", "#")
    desc = article.get("description") or ""
    image = article.get("urlToImage")

    date_raw = article.get("publishedAt")
    if date_raw:
        try:
            date_obj = datetime.strptime(date_raw, "%Y-%m-%dT%H:%M:%SZ")
            date_str = format_date(date_obj)
        except Exception:
            date_str = str(date_raw)
    else:
        date_str = ""

    # Clean up author formatting
    if author and author.strip() and author.strip().lower() != "none":
        byline = f"{author.strip()}, {source} | {date_str}"
    else:
        byline = f"{source} | {date_str}"

    # Build image tag only if lead article has a valid image URL
    has_valid_image = bool(is_lead and image and str(image).strip() and str(image).strip().lower() != "none")

    classes = ["article"]
    if is_lead:
        classes.append("lead")
    if has_valid_image:
        classes.append("has-image")

    cls_str = " ".join(classes)

    image_html = ""
    if has_valid_image:
        image_html = f"""
            <figure class='lead-image-wrap'>
                <img src='{image}' alt='{headline}' class='lead-image' loading='lazy'>
            </figure>"""

    article_html = f"""
        <article class='{cls_str}'>
            <div class='article-content'>
                <h3><a href='{link}' target='_blank' rel='noopener noreferrer'>{headline}</a></h3>
                <h4 class='byline'>{byline}</h4>
                <p>{desc}</p>
            </div>
            {image_html}
        </article>
    """
    return article_html


def build_section(section_name, articles):
    article_list = []
    for idx, article in enumerate(articles):
        article_html = build_article(article, is_lead=(idx == 0))
        article_list.append(article_html)

    articles_html = "\n".join(article_list)
    section_html = f"""
        <section class='newspaper-section'>
            <h2 class='section-header'>{section_name}</h2>
            <div class='articles-grid'>
                {articles_html}
            </div>
        </section>
    """
    return section_html


def build_page(articles_json, us_sources, stylesheet_path="newspaper.css", embed_css=True):
    articles = articles_json.get("articles", [])

    us_articles = [a for a in articles if a.get("source", {}).get("name") in us_sources]
    us_articles = sorted(us_articles, key=lambda a: a.get("publishedAt", ""), reverse=True)
    us_section = build_section("United States", us_articles)

    intl_articles = [a for a in articles if a.get("source", {}).get("name") not in us_sources]
    intl_articles = sorted(intl_articles, key=lambda a: a.get("publishedAt", ""), reverse=True)
    intl_section = build_section("World Dispatches", intl_articles)

    today_str = format_date(datetime.today(), include_day_of_week=True)

    css_block = ""
    if embed_css:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        css_file = os.path.join(project_root, stylesheet_path)
        if os.path.exists(css_file):
            try:
                with open(css_file, "r", encoding="utf-8") as f:
                    css_block = f"<style>\n{f.read()}\n    </style>"
            except Exception:
                pass

    page_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>The Air Monitor — {today_str}</title>
    <link rel="stylesheet" href="{stylesheet_path}">
    {css_block}
</head>
<body>
    <main class="newspaper-page">
        <header class="masthead">
            <div class="masthead-ear-bar">
                <span>Breathe Deep, Read Carefully</span>
                <span>Daily Circulation &bull; Two Cents</span>
            </div>
            <h1>The Air Monitor</h1>
            <div class="dateline-bar">
                <span>{today_str}</span>
                <span>All The Particulate Matter Fit To Measure</span>
                <span>Final Edition &bull; Vol. I, No. 1</span>
            </div>
        </header>

        {us_section}

        {intl_section}

        {footer}
    </main>
</body>
</html>
"""
    return page_html

