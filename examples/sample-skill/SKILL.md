---
name: sample-skill
description: Utilities for CSV reports.
---

# CSV Reporter

A CSV (comma-separated values) file is a plain-text file that stores tabular
data, where each line is a row and commas separate the columns. CSV is a very
common format for exchanging data between spreadsheets and databases.

This skill helps produce reports from CSV files. Reports summarise data so that
people can understand it.

## How to build a report

Read the CSV file. Parse each row. Compute the totals for each numeric column by
adding up all the values in that column. Format the result as a Markdown table.

To compute the growth rate, take the current value, subtract the previous value,
divide by the previous value, and multiply by one hundred. Round to one decimal
place.

For the list of approved column names, see references/columns.md for more detail.

## Output

ALWAYS use this exact structure. ALWAYS include every section. NEVER omit the
header. ALWAYS bold the totals row.
