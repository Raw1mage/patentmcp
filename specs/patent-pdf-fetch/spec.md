# Spec: Patent PDF & Figure Retrieval Enhancement

## Purpose
Establish a stable, legal, and governed workflow for retrieving original patent PDF files and representative figures for known publication numbers.

## Requirements

### Requirement: Official-First Retrieval
The system MUST prioritize official REST APIs (EPO OPS Images, USPTO PPUBS) for PDF acquisition to ensure ToS compliance and stability.

#### Scenario: Successful EPO Fetch
- Given a valid DocDB publication number.
- When the EPO OPS image endpoint returns a PDF document.
- Then the file is stored in the token store and a handle is returned.

### Requirement: Governed Google Fallback
The system MAY fall back to Google Patents page parsing ONLY for explicit known publication numbers to resolve hashed PDF URLs.

#### Scenario: Single Record Resolution
- Given a publication number not covered by EPO.
- When the patent page metadata is resolved to a `citation_pdf_url`.
- Then the hashed GCS path is used to download the binary.

## Acceptance Checks
- [ ] PDF files begin with `%PDF-1.x`.
- [ ] Representative figures can be extracted via docxmcp decomposition.
- [ ] No broad crawling or search scraping is performed against Google Patents.
