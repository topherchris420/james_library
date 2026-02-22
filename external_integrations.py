"""
R.A.I.N. Lab External Integrations

Tools for ArXiv, DOI lookup, and BibTeX generation.
"""

import re
import urllib.request
import urllib.parse
import json
import os


def search_arxiv(query: str, max_results: int = 5) -> str:
    """Search ArXiv for papers.

    Args:
        query: Search query
        max_results: Maximum number of results (default 5)

    Returns:
        Formatted ArXiv search results
    """
    try:
        # Use ArXiv API
        base_url = "http://export.arxiv.org/api/query"
        params = {
            # urlencode() below handles escaping; avoid double-encoding the query.
            "search_query": f"all:{query}",
            "max_results": max_results,
            "sortBy": "relevance",
            "sortOrder": "descending"
        }

        url = f"{base_url}?{urllib.parse.urlencode(params)}"

        with urllib.request.urlopen(url, timeout=10) as response:
            import xml.etree.ElementTree as ET
            xml_data = response.read().decode('utf-8')

        # Parse XML response
        root = ET.fromstring(xml_data)

        # ArXiv namespace
        ns = {'atom': 'http://www.w3.org/2005/Atom'}

        entries = root.findall('.//atom:entry', ns)

        if not entries:
            return f"No ArXiv results found for: {query}"

        results = [f"ArXiv Results for: {query}", "=" * 40]

        for i, entry in enumerate(entries, 1):
            title = entry.find('atom:title', ns).text.strip().replace('\n', ' ')
            summary = entry.find('atom:summary', ns).text.strip()[:200].replace('\n', ' ')
            author_elem = entry.findall('atom:author/atom:name', ns)
            authors = ", ".join([a.text for a in author_elem[:3]])
            if len(author_elem) > 3:
                authors += " et al."

            # Get PDF link
            links = entry.findall('atom:link', ns)
            pdf_link = ""
            for link in links:
                if link.get('title') == 'pdf':
                    pdf_link = link.get('href', '')
                    break

            arxiv_id = entry.find('atom:id', ns).text.split('/')[-1]

            results.append(f"""
{i}. {title}
   Authors: {authors}
   ID: {arxiv_id}
   Summary: {summary}...
   PDF: {pdf_link}
""")

        return "\n".join(results)

    except ImportError:
        return "Error: urllib not available"
    except Exception as e:
        return f"ArXiv search error: {e}"


def lookup_doi(doi: str) -> str:
    """Look up DOI information.

    Args:
        doi: DOI string (e.g., "10.1000/xyz123")

    Returns:
        Formatted DOI metadata
    """
    # Clean DOI
    doi = doi.strip()
    if doi.startswith("https://doi.org/"):
        doi = doi.replace("https://doi.org/", "")
    elif doi.startswith("http://dx.doi.org/"):
        doi = doi.replace("http://dx.doi.org/", "")

    try:
        # Use CrossRef API
        url = f"https://api.crossref.org/works/{urllib.parse.quote(doi)}"

        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))

        work = data.get('message', {})

        title = work.get('title', ['No title'])[0]
        authors = work.get('author', [])
        author_names = []
        for a in authors[:5]:
            given = a.get('given', '')
            family = a.get('family', '')
            author_names.append(f"{given} {family}".strip())
        author_str = ", ".join(author_names)
        if len(authors) > 5:
            author_str += " et al."

        # Get publication info
        published = work.get('published', work.get('published-print', {}))
        year = published.get('date-parts', [[None]])[0][0] if published else "Unknown"

        container = work.get('container-title', ['Unknown journal'])[0]

        # Get abstract if available
        abstract = work.get('abstract', '')
        if abstract:
            # Clean HTML tags
            abstract = re.sub(r'<[^>]+>', '', abstract)[:300]

        result = f"""DOI: {doi}
Title: {title}
Authors: {author_str}
Year: {year}
Journal: {container}"""

        if abstract:
            result += f"\nAbstract: {abstract}..."

        return result

    except urllib.error.HTTPError:
        return f"DOI not found: {doi}"
    except Exception as e:
        return f"DOI lookup error: {e}"


def generate_bibtex(paper_title: str, authors: str, year: str = None,
                    journal: str = None, doi: str = None,
                    arxiv_id: str = None) -> str:
    """Generate BibTeX entry from paper info.

    Args:
        paper_title: Paper title
        authors: Author string
        year: Publication year
        journal: Journal name
        doi: DOI
        arxiv_id: ArXiv ID

    Returns:
        BibTeX formatted entry
    """
    # Generate citation key
    first_author = authors.split(',')[0].split()[0] if authors else "Unknown"
    key_year = year if year else "unknown"
    cite_key = f"{first_author}{key_year}"

    # Build BibTeX
    entry_type = "misc"
    if arxiv_id:
        entry_type = "article"
    elif journal:
        entry_type = "article"

    lines = [f"@{entry_type}{{{cite_key},"]
    lines.append(f"  title = {{{paper_title}}},")
    lines.append(f"  author = {{{authors}}},")

    if year:
        lines.append(f"  year = {{{year}}},")
    if journal:
        lines.append(f"  journal = {{{journal}}},")
    if doi:
        lines.append(f"  doi = {{{doi}}},")
    if arxiv_id:
        lines.append(f"  eprint = {{{arxiv_id}}},")
        lines.append(f"  archivePrefix = {{arXiv}},")

    lines.append("}")

    return "\n".join(lines)


def get_paper_metadata(query: str) -> str:
    """Get paper metadata from query (tries ArXiv first, then DOI).

    Args:
        query: ArXiv ID, DOI, or search query

    Returns:
        Paper metadata
    """
    # Check if it's an ArXiv ID
    if re.match(r'\d{4}\.\d{4,5}', query):
        return search_arxiv(f"id:{query}", max_results=1)

    # Check if it's a DOI
    if '10.' in query and '/' in query:
        return lookup_doi(query)

    # Otherwise, search ArXiv
    return search_arxiv(query, max_results=3)
