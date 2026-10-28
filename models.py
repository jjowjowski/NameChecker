from dataclasses import dataclass, field


@dataclass
class Candidate:
    """A page some source thinks mentions the name. Not yet verified."""

    url: str
    title: str = ""
    outlet: str = ""
    published: str = ""  # YYYY-MM-DD, or "" if unknown
    sources: list[str] = field(default_factory=list)


@dataclass
class Mention:
    """A verified page, ready to become a sheet row."""

    url: str
    title: str
    outlet: str
    published: str
    sources: list[str]
    page_text: str
    type: str = "Other"
    how_mentioned: str = "Named"
    description: str = ""
