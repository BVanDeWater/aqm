import pandas as pd
import plotly.express as px

def generate_timeline(article_json):
    article_df = pd.DataFrame(article_json["articles"])
    article_df["source"] = article_df["source"].apply(lambda s: s["name"])

    fig = px.strip(article_df, x="publishedAt",
               hover_name="title",
               hover_data=["author", "source", "url"])
    fig.update_layout(title="Article Timeline")

    return fig