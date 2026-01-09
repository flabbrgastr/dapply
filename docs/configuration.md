# Configuration System

## Overview
The configuration system uses YAML files to define scraping parameters, URL patterns, and increment rules.

The URL configuration file (`urls.yaml`) contains an array of URL configurations, each with a specific type and parameters that define how the URL should be dynamically generated.

## URL Types

### 1. Static URLs
For simple, unchanging URLs that don't require any modifications.

```yaml
- name: "basic_shopping_site"
  url: "https://example-shop.com/products"
  type: "static"
```

### 2. Date-Based URLs
For URLs that include date parameters, such as daily deals or time-based reports.

```yaml
- name: "daily_deals"
  url: "https://example-shop.com/deals"
  type: "dated"
  date_format: "YYYY-MM-DD"
  date_range:
    start: "2023-01-01"
    end: "2023-12-31"
  date_parameter: "date"
```

### 3. Runner-Based URLs (Pagination)
For URLs that require iteration through pages or sequence numbers.

```yaml
- name: "product_listings"
  url: "https://example-shop.com/products"
  type: "runner"
  runner:
    parameter: "page"
    start: 1
    end: 100
    step: 1
    prefix: "?"
    separator: "="
```

### 4. Parameterized URLs
For URLs with multiple variable parameters that create different combinations.

```yaml
- name: "search_results"
  url: "https://example-shop.com/search"
  type: "parameterized"
  parameters:
    - name: "category"
      values: ["electronics", "clothing", "books"]
    - name: "sort"
      values: ["price_asc", "price_desc", "popularity"]
    - name: "limit"
      values: [20, 50, 100]
```

### 5. Complex URLs
For URLs that need multiple types of modifiers simultaneously.

```yaml
- name: "dynamic_product_feed"
  url: "https://api.example-shop.com/v1/products"
  type: "complex"
  modifiers:
    date:
      parameter: "updated_since"
      format: "YYYY-MM-DD"
      range:
        start: "2023-01-01"
        end: "2023-12-31"
    runner:
      parameter: "offset"
      start: 0
      end: 1000
      step: 50
    fixed:
      filters: "in_stock"
      api_key: "YOUR_API_KEY"
```

### 6. Variable-Based Templated URLs (NEW)
Using template variables like `$inc` that can be assigned different increment behaviors during scraping.

```yaml
# URL with increment variable ($inc)
- name: "erapo_pagination"
  url: "https://sxyprn.com/Dap.html?page=$inc"
  type: "templated"
  template_vars:
    inc:
      type: "increment"
      start: 0
      end: 5000
      step: 30

# URL with increment in path
- name: "analvids_videos"
  url: "https://www.analvids.com/new-videos/$inc"
  type: "templated"
  template_vars:
    inc:
      type: "increment"
      start: 1
      end: 100
      step: 1

# URL with multiple template variables
- name: "price_range_scraping"
  url: "https://shop.example.com/search?min_price=$min&max_price=$max&category=$cat&page=$page"
  type: "templated"
  template_vars:
    min:
      type: "increment"
      start: 0
      end: 500
      step: 50
    max:
      type: "increment"
      start: 100
      end: 1000
      step: 100
    cat:
      type: "options"
      values: ["electronics", "clothing", "books"]
    page:
      type: "increment"
      start: 1
      end: 10
      step: 1
```

### 7. Incremental URLs
For URLs with incremental IDs or numbers.

```yaml
- name: "product_details"
  url_base: "https://example-shop.com/product/"
  type: "incremental"
  incremental:
    start: 1000
    end: 2000
    prefix: ""
    suffix: ""
    padding: 0
```

### 8. Authenticated URLs
For URLs that require authentication headers or tokens.

```yaml
- name: "authenticated_data"
  url: "https://example-shop.com/api/data"
  type: "authenticated"
  auth:
    header: "Authorization"
    token_type: "Bearer"
    token: "YOUR_AUTH_TOKEN"
  parameters:
    date_from: "{start_date}"
    date_to: "{end_date}"
    page: "{page_num}"
  date_range:
    start: "2023-01-01"
    end: "2023-12-31"
    interval: "monthly"
  runner:
    parameter: "page_num"
    start: 1
    end: 50
```

## Core Configuration File: `urls.yaml`

The main configuration file defines URL templates with variable-based patterns.

### Template Variables
Variables are prefixed with `$` in URL templates:
- `$inc` - increment variable for pagination or sequences
- `$date` - date variable for time-based queries
- `$category` - categorical variable for filtering

### Increment Types
Different types of increment variables can be defined:

#### `increment` type
For numeric sequences:
```yaml
- name: "pagination_example"
  url: "https://example.com/items?page=$page"
  type: "templated"
  template_vars:
    page:
      type: "increment"
      start: 1
      end: 100
      step: 1
```

#### `options` type
For discrete value sets:
```yaml
- name: "category_example"
  url: "https://example.com/search?category=$cat&sort=$sort"
  type: "templated"
  template_vars:
    cat:
      type: "options"
      values: ["electronics", "clothing", "books"]
    sort:
      type: "options"
      values: ["relevance", "price", "rating"]
```

#### `date` type
For date ranges:
```yaml
- name: "daily_data_example"
  url: "https://api.example.com/data?date=$date"
  type: "templated"
  template_vars:
    date:
      type: "date"
      format: "YYYY-MM-DD"
      start: "2023-01-01"
      end: "2023-12-31"
```

## Configuration Schema

```yaml
urls:
  - name: "<unique_identifier>"
    url: "<url_template_with_$vars>"
    type: "templated"
    template_vars:
      <variable_name>:
        type: "<increment|options|date>"
        # Additional parameters based on type
```

## Best Practices

1. **Use descriptive names** for each URL configuration to make it clear what the purpose is.
2. **Group related URLs** together in the configuration file.
3. **Use appropriate date ranges** to avoid overloading servers or missing important data.
4. **Implement rate limiting** or delays between requests to be respectful to the target servers.
5. **Test configurations** with a small subset of data before running full scrapes.

## Common Dynamic URL Patterns in Shopping Sites

### Pagination Patterns
Many shopping sites use pagination to display large catalogs:

```yaml
# Standard pagination
- name: "standard_pagination"
  url: "https://shop.example.com/products"
  type: "runner"
  runner:
    parameter: "page"
    start: 1
    end: 100
    step: 1

# Offset-based pagination
- name: "offset_pagination"
  url: "https://api.shop.com/v1/products"
  type: "runner"
  runner:
    parameter: "offset"
    start: 0
    end: 5000
    step: 20
```

### Category-Based Patterns
Shopping sites often organize products by categories:

```yaml
# Category iteration
- name: "category_products"
  url: "https://shop.example.com/category/{category}"
  type: "templated"
  template_vars:
    category:
      values: ["electronics", "clothing", "home", "beauty", "sports"]

# Category with pagination
- name: "category_with_pagination"
  url: "https://shop.example.com/category/{category}"
  type: "parameterized"
  parameters:
    - name: "category"
      values: ["laptops", "phones", "tablets"]
  runner:
    parameter: "page"
    start: 1
    end: 50
    step: 1
```

### Price and Filter Patterns
Shopping sites often allow filtering by price ranges:

```yaml
# Price range filtering
- name: "price_filtered_products"
  url: "https://shop.example.com/search"
  type: "parameterized"
  parameters:
    - name: "min_price"
      values: [0, 50, 100, 200, 500]
    - name: "max_price"
      values: [50, 100, 200, 500, 1000]
    - name: "category"
      values: ["electronics", "clothing"]
```

### Time-Based Patterns
Some shopping sites show time-sensitive deals:

```yaml
# Daily deals
- name: "daily_specials"
  url: "https://shop.example.com/deals"
  type: "dated"
  date_format: "YYYY-MM-DD"
  date_range:
    start: "2023-01-01"
    end: "2023-12-31"
  date_parameter: "date"

# Hourly inventory updates
- name: "hourly_inventory"
  url: "https://api.shop.com/inventory"
  type: "dated"
  date_format: "YYYY-MM-DDTHH"
  date_range:
    start: "2023-01-01T00"
    end: "2023-01-02T23"
  date_parameter: "timestamp"
```

### Path-Based Incremental Patterns
Some sites use incremental numbers directly in the URL path:

```yaml
# Aalvids-style path incrementing
- name: "aalvids_videos"
  url_base: "https://www.aalvids.com/new-videos/"
  type: "incremental"
  incremental:
    start: 10
    end: 100
    prefix: ""
    suffix: ""
    padding: 0

# E-commerce path-based pagination
- name: "path_pagination"
  url_base: "https://shop.example.com/products/page/"
  type: "incremental"
  incremental:
    start: 1
    end: 50
    prefix: ""
    suffix: ""
    padding: 0
```

### Path Increment with Fixed Query Parameters
Some sites use incremental numbers in the path along with fixed query parameters:

```yaml
# Anvids-style with path increment and fixed parameters
- name: "anvids_filter"
  url_base: "https://www.anvids.com/filter/"
  type: "incremental"
  incremental:
    start: 1
    end: 100
    prefix: ""
    suffix: "?niche=doubnal&general=release"
    padding: 0
```

## Configuration Validation
- All variable names in the URL must be defined in `template_vars`
- Type-specific parameters must be valid for each increment type
- Start/end values must be logically consistent

## Implementation Notes

When implementing a scraper using this configuration:
- Parse the YAML file to extract all URL configurations
- For each configuration, generate the actual URLs based on the specified type and modifiers
- Apply appropriate delays between requests
- Handle errors gracefully and log any failed requests
- Respect robots.txt and rate limits of the target sites
- Consider implementing retry logic for failed requests
- Monitor for changes in URL patterns or site structure.