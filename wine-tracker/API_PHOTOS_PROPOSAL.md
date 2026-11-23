# Follow-up proposal: automatic wine intake and photographs

This is a proposal only. Phase 1 does not implement photograph endpoints.

The intended experience is: "Populate my wine library with relevant photos,"
"I've just bought this bottle," or an uploaded order confirmed as received.
The assistant extracts the details, creates or restocks the correct wine,
records the purchase price and quantity, finds a suitable photograph and
finishes with a summary. Routine matches do not require manual image approval.
Technical validation happens automatically.

Phase 1 already provides the create/update/stock primitives for this workflow.
The smallest additional server feature is an authenticated image-upload
endpoint for an existing wine, reusing the current upload directory, image
processing and `wines.image` field. Matching and order interpretation belong in
the assistant/client, not a second image-search system in Wine Tracker. Do not
add remote URL fetching to the initial endpoint.

1. Extract producer, wine name, vintage, quantity, bottle size and per-bottle
   price from the message or received order. Match existing records before
   creating anything. Distinguish case totals from bottle prices and received
   stock from an unreceived order. Use stable operation keys per order/line to
   avoid double additions when an order is processed again. Do not invent
   missing vintages or prices.
2. Search by producer, wine name and vintage, reusing Vivino search where
   suitable. Automatically attach a confidently matched photo from a permitted
   source, or use a supplied bottle photo. Prefer an exact vintage label; do
   not silently substitute a visibly different vintage. Search results alone
   are not evidence of permission to reuse a photograph. If a match is
   uncertain or reuse is not permitted, leave the image unchanged and mention
   it in the final summary while completing the other supported updates.
3. A trusted client uploads the validated image bytes to a proposed
   `POST /api/v1/wines/<id>/image` using the API credential and an idempotency
   key. The record must already exist; creating the wine uses Phase 1 first.
4. Enforce a modest byte limit (for example 5 MiB), pixel/dimension limits and
   actual decoding with Pillow; reject deceptive MIME types/extensions,
   truncated files, SVG and decompression bombs. Initially allow JPEG, PNG and
   WebP. Re-encode to strip metadata and produce a safe generated filename.
5. Update only the image reference. Preserve quantity, notes and all other
   fields. "Populate photos" fills missing images by default; an instruction
   to refresh existing photos can authorize replacement without per-image
   approval.
   Stage the validated file first; atomically update the image reference and
   retry receipt, cleaning up failed staging files. Account for references
   from other wines/chat before deleting the previous file.
6. Existing ZIP backups already include referenced files in the upload
   directory. Verify backup/restore with tests for API-attached images and
   retry safety, plus authorization, bad inputs and field preservation.
7. Read back changed records and report a concise completion summary: wines
   added/restocked, bottles and prices recorded, photos attached and sources,
   existing records left alone, and any missing or uncertain matches. This is
   a completion report, not a mandatory manual validation queue.

If server-side remote downloads are later needed, add them separately with
source allowlisting, HTTPS, redirect validation, DNS/private-address checks,
timeouts and streaming size limits to prevent SSRF. Record source/permission
information without overwriting personal notes. That may warrant a small
metadata table, to be reviewed with the upstream maintainer.

Review the Phase 1 API before implementing this proposal. Test order replays,
existing-wine matching, case pricing, partial failures and uncertain image
matches in addition to the image endpoint itself.
