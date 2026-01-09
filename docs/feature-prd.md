# Feature-Specific PRD: Orchestator, Scraper, and Enhanced Analytics Module

## Feature Overview
The orchestator module coordinates the complete web scraping workflow between URL generation and scraping components. The scraper module performs HTTP scraping and stores content in data/scrapes/ with organized directory structure by crawl session and domain. The enhanced analytics module will provide comprehensive data analysis and visualization capabilities for scraped content.

## Objectives

### Orchestator Module:
- Coordinate workflow between URL generation and scraping
- Manage status tracking and monitoring
- Handle error propagation and retry logic
- Support organized storage with cleanup procedures

### Scraper Module:
- Scrape URLs and store content in data/scrapes/ directory with organized structure
- Support configurable delays between scrapes
- Allow different scraper types per URL
- Maintain modular architecture for future updates

### Analytics Module:
- Provide detailed analytics on scraping performance
- Visualize success/failure rates over time
- Analyze scraped data patterns and trends
- Generate automated reports

## Technical Requirements

### Orchestator Module:
- Integrate with URL generator to get list of URLs to process
- Hand off URLs to scraper module with configurable concurrency
- Update status tracking based on scrape results
- Provide status summary and monitoring capabilities
- Support organized storage with crawl sessions and domain-based structure
- Support cleanup of old crawl directories

### Scraper Module:
- Save scraped content to data/scrapes/ directory with metadata
- Support configurable delay between scrapes (seconds)
- Support different scraper types per URL (default, bs for BeautifulSoup, w3m for text browser, js for JavaScript-heavy sites)
- Modular design allowing easy addition of new scraper types
- Content storage with hash-based filenames and metadata
- Organized by crawl sessions and domain for human identifiability
- Extract only body content from HTML to reduce file size
- Include metadata in saved files (source URL, timestamp, domain, crawl session)

### Analytics Module:
- Capture metadata about each scraping operation
- Record timing, response sizes, status codes
- Track resource usage and performance metrics
- Design efficient storage for scraping metadata

## Implementation Plan

### Phase 1: Orchestator Implementation (COMPLETED)
- [x] Design orchestator module interface
- [x] Implement URL generation coordination
- [x] Integrate with scraper module
- [x] Connect to status tracking system
- [x] Add error handling and monitoring
- [x] Implement organized storage with crawl sessions
- [x] Add cleanup procedures for old crawls

### Phase 2: Scraper Module Implementation (COMPLETED)
- [x] Implement basic scraping functionality
- [x] Add content saving to data/scrapes/ directory
- [x] Support configurable delays between scrapes
- [x] Implement different scraper types per URL
- [x] Add BeautifulSoup scraper type for clean text extraction
- [x] Add W3M scraper type for text browser rendering
- [x] Design modular architecture for future updates
- [x] Add metadata to saved files
- [x] Organize files with domain-based structure
- [x] Implement body-only extraction for HTML content
- [x] Add configurable user agents and timeouts

### Phase 3: Analytics Data Collection Enhancement
- [ ] Extend Orchestator to collect metadata
- [ ] Add timing and performance tracking
- [ ] Implement response analytics

### Phase 4: Storage Architecture
- [ ] Design schema for metadata storage
- [ ] Implement data retention mechanisms
- [ ] Optimize for analytical queries

### Phase 5: Analytics Processing
- [ ] Develop calculation algorithms
- [ ] Implement aggregation functions
- [ ] Create trend analysis capabilities

### Phase 6: Visualization Components
- [ ] Design dashboard UI components
- [ ] Implement charting capabilities
- [ ] Create export functionality

## Non-Functional Requirements
- Performance impact under 10% on scraping operations
- Support for configurable concurrency levels
- Support for configurable delays between requests
- Support for different scraper types per URL
- Support for up to 1M+ scraped records
- Data retention policy configuration
- Export performance for datasets up to 100K records

## Success Criteria
- Orchestator module coordinating workflow successfully
- Scraper module saving content to data/scrapes/ with metadata
- Configurable delays and scraper types per URL working
- Organized storage with crawl sessions and domain structure
- Analytics dashboard operational within 2 weeks
- Performance impact <10% measured
- Historical data retention configurable
- Export functionality working for all major formats