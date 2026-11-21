"""Small, dependency-free retrieval over local Markdown policy files."""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from enterprise_os.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

MAX_POLICY_FILES = 100
MAX_POLICY_FILE_BYTES = 1_000_000
MAX_EXCERPT_CHARACTERS = 4_000
DEFAULT_RESULT_COUNT = 4

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_WORD = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_STOP_WORDS = frozenset(
    {
        "a", "about", "an", "and", "are", "as", "at", "be", "but", "by", "can",
        "company", "do", "does", "for", "from", "had", "has", "have", "how", "i",
        "if", "in", "is", "it", "me", "my", "of", "on", "or", "our", "please",
        "question", "record", "records", "the", "their", "them", "there", "these",
        "this", "those", "to", "us", "was", "we", "were", "what", "when", "where",
        "which", "who", "why", "will", "with", "you", "your", "tell", "check",
        "ticket", "tickets", "employee", "employees", "policy", "policies", "whether",
    }
)
_SYNONYMS = {
    "reimburse": "refund",
    "reimbursed": "refund",
    "reimbursement": "refund",
    "reimbursements": "refund",
    "moneyback": "refund",
    "returns": "return",
    "returned": "return",
    "returning": "return",
    "violates": "violate",
    "violated": "violate",
    "violating": "violate",
}


class PolicySearchError(RuntimeError):
    """Raised when local policy documents cannot be read safely."""


@dataclass(frozen=True, slots=True)
class PolicyExcerpt:
    """A matched, bounded Markdown section with its source metadata."""

    source: str
    title: str
    section: str
    content: str
    score: int

    def to_dict(self) -> dict[str, str | int]:
        """Return a serializable representation for the graph state."""
        return {
            "source": self.source,
            "title": self.title,
            "section": self.section,
            "content": self.content,
            "score": self.score,
        }


def _normalize_term(term: str) -> str:
    """Apply lightweight normalization without an NLP dependency."""
    normalized = _SYNONYMS.get(term, term)
    if normalized.endswith("ies") and len(normalized) > 4:
        normalized = f"{normalized[:-3]}y"
    elif normalized.endswith("ing") and len(normalized) > 5:
        normalized = normalized[:-3]
    elif normalized.endswith("ed") and len(normalized) > 4:
        normalized = normalized[:-2]
    elif normalized.endswith("s") and len(normalized) > 4:
        normalized = normalized[:-1]
    return normalized


def _terms(text: str) -> set[str]:
    """Return normalized content terms after removing common filler words."""
    return {
        normalized
        for token in _WORD.findall(text.casefold())
        if (normalized := _normalize_term(token)) not in _STOP_WORDS
        and len(normalized) > 1
    }


def _markdown_sections(text: str, fallback_title: str) -> tuple[str, list[tuple[str, str]]]:
    """Split a Markdown document into heading-based text sections."""
    title = fallback_title
    current_section = "Overview"
    current_lines: list[str] = []
    sections: list[tuple[str, str]] = []

    def append_section() -> None:
        body = "\n".join(current_lines).strip()
        if body:
            sections.append((current_section, body[:MAX_EXCERPT_CHARACTERS]))

    for line in text.splitlines():
        heading = _HEADING.match(line.strip())
        if heading is None:
            current_lines.append(line)
            continue

        append_section()
        current_lines = []
        heading_level = len(heading.group(1))
        heading_text = heading.group(2).strip()[:200]
        if heading_level == 1:
            title = heading_text
            current_section = "Overview"
        else:
            current_section = heading_text

    append_section()
    if not sections and text.strip():
        sections.append(("Document", text.strip()[:MAX_EXCERPT_CHARACTERS]))
    return title, sections


def _load_policy_excerpts(policy_directory: Path) -> list[PolicyExcerpt]:
    """Read bounded Markdown sections from the configured local policy folder."""
    try:
        if not policy_directory.is_dir():
            return []
        root = policy_directory.resolve(strict=True)
        paths = sorted(policy_directory.glob("*.md"), key=lambda item: item.name.casefold())
        if len(paths) > MAX_POLICY_FILES:
            raise PolicySearchError(
                f"The policy folder contains more than {MAX_POLICY_FILES} Markdown files."
            )

        excerpts: list[PolicyExcerpt] = []
        for path in paths:
            try:
                resolved_path = path.resolve(strict=True)
                if not resolved_path.is_relative_to(root):
                    logger.warning("Ignoring policy file outside the policy folder.")
                    continue
                raw_content = resolved_path.read_bytes()
                if len(raw_content) > MAX_POLICY_FILE_BYTES:
                    raise PolicySearchError(
                        f"Policy file {path.name} exceeds the 1 MB safety limit."
                    )
                text = raw_content.decode("utf-8")
            except PolicySearchError:
                raise
            except (OSError, UnicodeError) as exc:
                raise PolicySearchError(
                    f"Policy file {path.name} could not be read as UTF-8."
                ) from exc

            fallback_title = path.stem.replace("_", " ").title()[:200]
            title, sections = _markdown_sections(text, fallback_title)
            for section, content in sections:
                excerpts.append(
                    PolicyExcerpt(
                        source=path.name,
                        title=title,
                        section=section,
                        content=content,
                        score=0,
                    )
                )
        return excerpts
    except PolicySearchError:
        raise
    except OSError as exc:
        logger.error("Policy folder read failed (%s).", type(exc).__name__)
        raise PolicySearchError("The local policy folder could not be read.") from exc
    except Exception as exc:
        logger.error("Policy retrieval failed (%s).", type(exc).__name__)
        raise PolicySearchError("Local policy retrieval failed. Please retry.") from exc


def retrieve_policy(
    query: str,
    policy_directory: Path | None = None,
    result_count: int = DEFAULT_RESULT_COUNT,
) -> list[dict[str, str | int]]:
    """Rank policy sections by normalized lexical relevance and return top matches."""
    if not isinstance(query, str) or not query.strip():
        return []
    if not isinstance(result_count, int) or not 1 <= result_count <= 10:
        raise PolicySearchError("Policy result count must be between 1 and 10.")

    directory = policy_directory or PROJECT_ROOT / "data" / "policies"
    query_terms = _terms(query[:3_000])
    if not query_terms:
        return []

    excerpts = _load_policy_excerpts(Path(directory))
    ranked: list[PolicyExcerpt] = []
    try:
        for excerpt in excerpts:
            content_terms = _terms(
                f"{excerpt.title} {excerpt.section} {excerpt.content}"
            )
            matched_terms = query_terms & content_terms
            if matched_terms:
                title_terms = _terms(f"{excerpt.title} {excerpt.section}")
                score = sum(2 if term in title_terms else 1 for term in matched_terms)
                ranked.append(
                    PolicyExcerpt(
                        source=excerpt.source,
                        title=excerpt.title,
                        section=excerpt.section,
                        content=excerpt.content,
                        score=score,
                    )
                )
        ranked.sort(key=lambda item: (-item.score, item.source.casefold(), item.section.casefold()))
        return [item.to_dict() for item in ranked[:result_count]]
    except Exception as exc:
        logger.error("Policy ranking failed (%s).", type(exc).__name__)
        raise PolicySearchError("Local policy ranking failed. Please retry.") from exc
