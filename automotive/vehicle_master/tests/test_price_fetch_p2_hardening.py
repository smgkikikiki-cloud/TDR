from vehreg.price_fetch import USER_AGENT, parse_page_metadata


def test_fetch_user_agent_matches_robots_audit_token() -> None:
    assert USER_AGENT.split("/", 1)[0] == "tdr-automotive"


def test_localised_document_dates_are_unknown_not_fetch_errors() -> None:
    metadata = parse_page_metadata("""
    <html><head>
      <meta property="og:title" content="Pilot">
      <meta property="article:published_time" content="2 กันยายน 2569">
      <meta property="article:modified_time" content="9 กันยายน 2569">
    </head><body>hello</body></html>
    """)

    assert metadata.title == "Pilot"
    assert metadata.published_at is None
    assert metadata.modified_at is None
