#!/usr/bin/env python3
"""
Awesome List Linter and Validator for Awesome Agentic Growth & Marketing Skills.

This tool validates and formats the README.md file according to repository guidelines:
1. Enforces alphabetical sorting of entries within each category section.
2. Checks for duplicate links (URLs) and project names across categories.
3. Enforces standard list item formatting: `- [Name](URL) - Description.`
4. Verifies Table of Contents entries match section headers.
5. Optionally checks HTTP status for all URLs using concurrent requests (`--check-links`).
6. Provides an automatic fixing capability (`--fix`) to sort and format entries.

Usage:
    python scripts/lint_awesome.py [README.md] [--fix] [--check-links] [--strict]
"""

import argparse
import concurrent.futures
import re
import sys
import time
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple, NamedTuple


class Entry(NamedTuple):
    raw_line: str
    name: str
    url: str
    description: str


class LintIssue(NamedTuple):
    level: str  # 'ERROR', 'WARNING', 'INFO'
    section: str
    message: str
    line_number: Optional[int] = None


# Pattern for matching standard awesome list entries: `- [Name](URL) - Description`
ENTRY_PATTERN = re.compile(
    r'^\s*-\s*\[(?P<name>[^\]]+)\]\((?P<url>https?://[^\)]+)\)\s*-\s*(?P<desc>.+?)\s*$'
)

# Pattern for section headers: `## Section Title`
HEADER_PATTERN = re.compile(r'^##\s+(?P<title>.+?)\s*$')

# Sections that should not have their list items sorted or validated as entry categories
EXCLUDED_SECTIONS = {
    'contents',
    'contributing',
    'pull request checklist',
    'what belongs here',
    'what does not belong here',
    'add an entry',
    'review process',
    'license',
    'acknowledgments',
}


def parse_entry(line: str) -> Optional[Entry]:
    """Parse a single Markdown list line into an Entry namedtuple if it matches entry format."""
    match = ENTRY_PATTERN.match(line)
    if not match:
        return None
    return Entry(
        raw_line=line.strip(),
        name=match.group('name').strip(),
        url=match.group('url').strip(),
        description=match.group('desc').strip(),
    )


def extract_sections(content: str) -> Dict[str, List[Tuple[int, str]]]:
    """
    Parse Markdown content into sections mapping section header titles to lists of (line_num, line_str).
    Lines preceding the first header are stored under header '' (empty string).
    """
    sections: Dict[str, List[Tuple[int, str]]] = {}
    current_section = ''
    sections[current_section] = []

    lines = content.splitlines()
    for line_idx, line in enumerate(lines, start=1):
        header_match = HEADER_PATTERN.match(line)
        if header_match:
            current_section = header_match.group('title').strip()
            if current_section not in sections:
                sections[current_section] = []
        else:
            sections[current_section].append((line_idx, line))

    return sections


def validate_toc(content: str) -> List[LintIssue]:
    """Verify that entries in Table of Contents (`## Contents`) match actual section headers."""
    issues: List[LintIssue] = []
    sections = extract_sections(content)

    if 'Contents' not in sections:
        issues.append(LintIssue('WARNING', 'TOC', 'Table of Contents section (## Contents) not found.'))
        return issues

    # Extract anchor links from TOC lines (e.g., `- [Title](#title)`)
    toc_lines = [line for _, line in sections['Contents']]
    toc_links = re.findall(r'\[([^\]]+)\]\(#([^\)]+)\)', '\n'.join(toc_lines))

    # All level-2 headers except 'Contents'
    actual_headers = [title for title in sections.keys() if title and title.lower() != 'contents']

    for link_text, anchor in toc_links:
        # Check if anchor corresponds to a header in actual_headers
        slugified_headers = [
            h.lower().replace(' ', '-').replace(',', '').replace('.', '').replace('&', '') for h in actual_headers
        ]
        if anchor.lower() not in slugified_headers:
            issues.append(
                LintIssue('WARNING', 'TOC', f'TOC entry "{link_text}" (anchor: #{anchor}) has no matching section header.')
            )

    return issues


def validate_formatting_and_order(content: str) -> Tuple[List[LintIssue], Dict[str, List[Entry]]]:
    """
    Analyze document content for formatting errors, non-alphabetized categories, and duplicate links.
    Returns a list of LintIssues and a dictionary mapping category title -> list of Entry objects.
    """
    issues: List[LintIssue] = []
    category_entries: Dict[str, List[Entry]] = {}
    seen_urls: Dict[str, Tuple[str, int]] = {}  # url -> (section, line_number)
    seen_names: Dict[str, Tuple[str, int]] = {}  # name -> (section, line_number)

    sections = extract_sections(content)

    for section_title, line_tuples in sections.items():
        if not section_title or section_title.lower() in EXCLUDED_SECTIONS:
            continue

        entries_in_section: List[Entry] = []

        for line_num, line in line_tuples:
            stripped = line.strip()
            # Ignore horizontal rules like ---
            if stripped.startswith('---') or stripped.startswith('***') or stripped.startswith('___'):
                continue
            if not stripped.startswith('-'):
                continue

            entry = parse_entry(line)
            if not entry:
                issues.append(
                    LintIssue(
                        'ERROR',
                        section_title,
                        f'List item does not follow format `- [Name](URL) - Description.`: `{line.strip()}`',
                        line_num,
                    )
                )
                continue

            # Check description ending punctuation (ignoring trailing markdown emphasis/parentheticals)
            desc = entry.description
            clean_desc = re.sub(r'[\s\*\_]+$', '', desc)
            if not (clean_desc.endswith('.') or clean_desc.endswith('!') or clean_desc.endswith('?') or clean_desc.endswith(')')):
                issues.append(
                    LintIssue(
                        'WARNING',
                        section_title,
                        f'Entry "{entry.name}" description does not end with punctuation: "{desc}"',
                        line_num,
                    )
                )

            # Check duplicate URLs
            if entry.url in seen_urls:
                prev_section, prev_line = seen_urls[entry.url]
                issues.append(
                    LintIssue(
                        'ERROR',
                        section_title,
                        f'Duplicate URL "{entry.url}" (previously seen in "{prev_section}" at line {prev_line})',
                        line_num,
                    )
                )
            else:
                seen_urls[entry.url] = (section_title, line_num)

            # Check duplicate entry names
            name_key = entry.name.lower()
            if name_key in seen_names:
                prev_section, prev_line = seen_names[name_key]
                issues.append(
                    LintIssue(
                        'WARNING',
                        section_title,
                        f'Duplicate project name "{entry.name}" (previously seen in "{prev_section}" at line {prev_line})',
                        line_num,
                    )
                )
            else:
                seen_names[name_key] = (section_title, line_num)

            entries_in_section.append(entry)

        category_entries[section_title] = entries_in_section

        # Check alphabetical sorting by project name
        entry_names = [e.name.lower() for e in entries_in_section]
        sorted_names = sorted(entry_names)
        if entry_names != sorted_names:
            issues.append(
                LintIssue(
                    'ERROR',
                    section_title,
                    f'Entries in section "{section_title}" are not sorted alphabetically by project name.',
                )
            )

    return issues, category_entries


def check_url_status(url: str, timeout: int = 10, retries: int = 2) -> Tuple[str, int]:
    """Check HTTP response status code for a single URL using HEAD or GET request with retries."""
    for attempt in range(retries + 1):
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0 (compatible; awesome-growth-hacking-linter/1.0)'},
            method='HEAD',
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return url, resp.getcode()
        except urllib.error.HTTPError as e:
            # Fallback to GET if HEAD fails (e.g. 405 Method Not Allowed, 403 Forbidden, 429 Too Many Requests, 400 Bad Request)
            if e.code in (405, 403, 429, 400):
                try:
                    get_req = urllib.request.Request(
                        url,
                        headers={'User-Agent': 'Mozilla/5.0 (compatible; awesome-growth-hacking-linter/1.0)'},
                        method='GET',
                    )
                    with urllib.request.urlopen(get_req, timeout=timeout) as resp:
                        return url, resp.getcode()
                except urllib.error.HTTPError as get_e:
                    if attempt == retries:
                        return url, get_e.code
                except Exception:
                    if attempt == retries:
                        return url, 0
            else:
                if attempt == retries:
                    return url, e.code
        except Exception:
            if attempt == retries:
                return url, 0

        if attempt < retries:
            time.sleep(1.0 * (attempt + 1))

    return url, 0


def check_links_health(
    urls: List[str], max_workers: int = 5
) -> Dict[str, int]:
    """Validate HTTP health for a list of URLs concurrently."""
    results: Dict[str, int] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_url = {executor.submit(check_url_status, url): url for url in urls}
        for future in concurrent.futures.as_completed(future_to_url):
            url, status = future.result()
            results[url] = status
    return results


def fix_readme_sorting(content: str) -> str:
    """
    Sort entries alphabetically in each category section of the document while preserving
    surrounding Markdown text, comments, and headers.
    """
    lines = content.splitlines()
    new_lines: List[str] = []
    idx = 0
    num_lines = len(lines)
    current_section = ''

    while idx < num_lines:
        line = lines[idx]
        header_match = HEADER_PATTERN.match(line)

        if header_match:
            current_section = header_match.group('title').strip()
            new_lines.append(line)
            idx += 1
            continue

        # If we are in a sortable section and encounter a block of list entries
        if (
            current_section
            and current_section.lower() not in EXCLUDED_SECTIONS
            and ENTRY_PATTERN.match(line)
        ):
            # Collect contiguous block of list entries
            entry_block: List[Entry] = []
            non_entry_lines_in_block: List[str] = []

            while idx < num_lines:
                curr_line = lines[idx]
                stripped = curr_line.strip()
                if HEADER_PATTERN.match(curr_line) or stripped.startswith('---') or stripped.startswith('***') or stripped.startswith('___'):
                    break
                entry = parse_entry(curr_line)
                if entry:
                    entry_block.append(entry)
                elif stripped.startswith('-'):
                    non_entry_lines_in_block.append(curr_line)
                elif not stripped:
                    # Empty line ends entry block
                    break
                else:
                    non_entry_lines_in_block.append(curr_line)
                idx += 1

            # Sort entries by name (case-insensitive)
            sorted_entries = sorted(entry_block, key=lambda e: e.name.lower())
            for e in sorted_entries:
                new_lines.append(f'- [{e.name}]({e.url}) - {e.description}')

            for non_entry in non_entry_lines_in_block:
                new_lines.append(non_entry)

            continue

        new_lines.append(line)
        idx += 1

    return '\n'.join(new_lines) + ('\n' if content.endswith('\n') else '')


def main():
    parser = argparse.ArgumentParser(
        description='Awesome List Linter and Validator for awesome-growth-hacking-skills.'
    )
    parser.add_argument(
        'file',
        nargs='?',
        default='README.md',
        help='Path to README.md file (default: README.md)',
    )
    parser.add_argument(
        '--fix',
        action='store_true',
        help='Automatically sort list entries alphabetically within categories.',
    )
    parser.add_argument(
        '--check-links',
        action='store_true',
        help='Check HTTP status of all links in the document.',
    )
    parser.add_argument(
        '--strict',
        action='store_true',
        help='Exit with non-zero status if any errors or warnings are found.',
    )
    parser.add_argument(
        '--quiet',
        '-q',
        action='store_true',
        help='Suppress non-error messages.',
    )

    args = parser.parse_args()

    try:
        with open(args.file, 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        print(f'Error: File not found: {args.file}', file=sys.stderr)
        sys.exit(1)

    if args.fix:
        if not args.quiet:
            print('Sorting and formatting entries in README.md...')
        fixed_content = fix_readme_sorting(content)
        with open(args.file, 'w', encoding='utf-8') as f:
            f.write(fixed_content)
        content = fixed_content
        if not args.quiet:
            print('Successfully updated README.md.')

    toc_issues = validate_toc(content)
    format_issues, category_entries = validate_formatting_and_order(content)
    all_issues = toc_issues + format_issues

    errors = [i for i in all_issues if i.level == 'ERROR']
    warnings = [i for i in all_issues if i.level == 'WARNING']

    if not args.quiet:
        print(f'--- LINT SUMMARY ---')
        print(f'Categories checked: {len(category_entries)}')
        total_entries = sum(len(entries) for entries in category_entries.values())
        print(f'Total entries validated: {total_entries}')
        print(f'Errors: {len(errors)}, Warnings: {len(warnings)}')

        if all_issues:
            print('\n--- ISSUES FOUND ---')
            for issue in all_issues:
                line_info = f' (line {issue.line_number})' if issue.line_number else ''
                print(f'[{issue.level}] [{issue.section}]{line_info}: {issue.message}')

    if args.check_links:
        all_urls = [
            entry.url
            for entries in category_entries.values()
            for entry in entries
        ]
        if not args.quiet:
            print(f'\nChecking HTTP health for {len(all_urls)} URLs...')
        link_results = check_links_health(all_urls)
        unhealthy = {url: code for url, code in link_results.items() if not (200 <= code < 400)}

        if not args.quiet:
            print(f'Link check completed: {len(all_urls) - len(unhealthy)}/{len(all_urls)} reachable.')
            if unhealthy:
                print('\n--- UNREACHABLE LINKS ---')
                for url, code in unhealthy.items():
                    print(f'Status {code}: {url}')

        if unhealthy:
            errors.append(
                LintIssue('ERROR', 'Links', f'Found {len(unhealthy)} unreachable or broken link(s).')
            )

    has_failures = bool(errors) or (args.strict and bool(warnings))
    if has_failures:
        if not args.quiet:
            print('\nLint validation failed.', file=sys.stderr)
        sys.exit(1)
    else:
        if not args.quiet:
            print('\nLint validation passed successfully!')
        sys.exit(0)


if __name__ == '__main__':
    main()
