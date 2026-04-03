# UTCP Tool Best Practices

## Understanding Error Responses

All UTCP tool calls return JSON. Errors appear as `{"error": "<message>"}`.
Read the error message carefully before deciding your next action.

## Error Handling

### Permission Errors (403 Forbidden)

Messages containing "Forbidden", "403", "unauthorized", or "access denied" indicate a **hard permission boundary**.

- **Do NOT retry** — the permission will not change during this session
- Record the permission limitation as a finding (e.g., "403 on readCoreV1NodeStatus — RBAC denies node access")
- Continue investigating using resources you DO have access to
- If the error is namespace-scoped, try other namespaces only if relevant to the investigation

### Not Found (404)

Messages containing "not found", "404", or "does not exist".

- Do NOT retry with the same parameters
- Verify the resource name, namespace, and API operation are correct
- Use `search_<service>_operations` to find the correct operation name
- If the resource genuinely doesn't exist, record that as a finding and move on

### Server Errors (500, 502, 503)

Messages containing "500", "Internal Server Error", "Bad Gateway", or "Service Unavailable" may be transient.

- ONE retry is acceptable
- If the retry also fails, record the error and move on
- Do NOT retry more than once

### Invalid Request (400, 422)

Messages containing "400", "Bad Request", "422", or "validation" indicate incorrect parameters.

- Do NOT retry with the same parameters
- Use `get_<service>_operation_details` to check the correct parameter schema
- Fix the parameters and try again

## Tool Discovery

Before calling an unfamiliar operation:
1. `list_<service>_operations` — browse available operations (filter by tag if relevant)
2. `search_<service>_operations` — find the right operation by keyword
3. `get_<service>_operation_details` — understand required parameters
4. Only then call the operation with correct parameters

## Efficiency Rules

- Never call the same failing tool more than twice with identical parameters
- Discover operations first, then execute — don't interleave discovery with repeated failed calls
- Prefer specific get/describe operations over listing entire collections
