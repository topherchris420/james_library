## 2025-02-14 - Pre-computing Lowercase Content
**Learning:** Text lowercasing for fuzzy matching in a loop is expensive (O(N * K)). Pre-computing it during load (O(N)) yields significant speedups (5x) for frequent lookups.
**Action:** When performing repeated case-insensitive searches on static content, always cache the normalized version.

## 2025-02-14 - Concatenated Global Search Index
**Learning:** Iterating through hundreds of large strings in Python to check substring existence (O(N*M)) incurs significant interpreter overhead. Concatenating them into a single global index string with delimiters allows Python's C-optimized `find` to search once (O(Total_M)), providing massive speedups (especially for "not found" cases).
**Action:** When searching for a substring across many documents where the first match suffices, concatenate the documents into a single search index with delimiters and use binary search to map back to the source document.
