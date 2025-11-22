just some notes.

The verification was attempted with Claude Code Sonnet 4.5 (failed), Gemini CLI 2.5 pro (failed), and Codex gpt5.1 high (succeeded).

* The Semgrep agent doesn’t have access to backend logic, so it can’t reliably verify though it did a great job of identifying false positives from SAST.
* The models often fixate on a single idea and claim a vulnerability exists even when they can’t provide evidence or a valid proof-of-concept.
* At one point, the agent tried to disable the SSRF protection on the server itself — interesting behavior, but irrelevant to our benchmark.
* What **worked extremely well** in my case was prompting the agent to search for similar vulnerabilities: past issues, bug patterns, or multi-step chains that could combine to form a more impactful exploit.
    * I only prompted this after the agent admitted that disabling SSRF protection wasn’t a valid or realistic vulnerability. This prompt led to the real SSRF vulnerability.

Model Output for the above prompt
```text
> You’re right to ask “how could this be truly exploitable without changing backend settings?” Here are realistic chains and edge cases that
don’t rely on arbitrarily weakening the server but do leverage common defaults, known quirks, or features many admins enable.

  1) IPv6 SSRF Bypass (plugin caveat)

  - What: The SSRF protection used by Graby (j0k3r/httplug-ssrf-plugin) explicitly notes it uses gethostbynamel (IPv4 only). That means IPv6
  literal URLs can slip through if the HTTP stack prefers IPv6.
  - Why it matters: Private/internal IPv6 (e.g., [::1], link-local) may be reachable when IPv4 is blocked.
  - Test idea:
      - Android share: http://[::1]:8181/article.html (or another IPv6-accessible internal service).
      - Observe internal service logs or tcpdump from the target to confirm a GET.
  - Mitigation: Ensure the SSRF layer validates IPv6 literals and IPv6-resolved domains and rejects loopback/link-local ULA ranges.

  2) Image Caching Fetches (SSRF via images)

  - What: The initial article fetch uses Graby with SSRF protection. But image downloading is done by Wallabag\Helper\DownloadImages which
  uses Symfony\Contracts\HttpClient\HttpClientInterface directly (no SSRF plugin in that path).
  - Impact: If “download images” is enabled on the server (common in many deployments), HTML that includes <img
  src="http://127.0.0.1:XXXX/..."> or other internal targets will be fetched server-side even though the main article fetch was vetted.
  - Why it pairs well: Your exported Android AddUrlProxyActivity lets a malicious app silently add a URL to your list. The attacker hosts a
  page that includes internal image URLs; the server then fetches those images, pivoting into the private network.
  - Verification steps:
      - On server: Enable “download images to local” (if it’s already on, no change needed).
      - Host a page externally that returns <img src="http://127.0.0.1:8181/ssrf.jpg">.
      - Share the page via Android; check internal service logs for the fetch.
  - Mitigation: Route ALL outbound fetches (including image downloads, OG images, etc.) through the SSRF protection layer and enforce IP
  allow/deny policies uniformly.

  3) Redirect/Meta-chain SSRF (unchanged settings)

  - What: Graby follows redirects (via RedirectPlugin). If SSRF checks don’t re-run on each hop (or only validate the initial host), an
  external URL could 302 to an internal host or to an IPv6 literal.
  - Reality check: In the code path, the plugin is a client-side plugin added before RedirectPlugin, so it should run per request, but you
  should still test:
      - External URL → 302 to http://[::1]:8181/... (IPv6 literal).
  - Mitigation: Enforce SSRF checks on every redirect hop; reject any hop that resolves to private/localhost (both IPv4 and IPv6).

  4) WebView + JavaScript Interfaces (client-side abuse)

  - What: ReadArticleActivity’s WebView:
      - Enables JavaScript (setJavaScriptEnabled(true)).
      - Always exposes hostWebViewTextController (via addJavascriptInterface) and conditionally hostAnnotationController (when annotations
  are enabled).
      - Loads article HTML into WebView (loadDataWithBaseURL("file:///android_asset/", ...)).
  - Why it matters: If Graby returns HTML with attacker-controlled scripts (or if it misses script sanitization for a site), JS runs in the
  app and can call those exposed interfaces. Even if interfaces are limited, that’s a real UX/security issue independent of SSRF. Also, when
  “image cache” is on, WebView file access is enabled.
  - Practical risk: Attacker silently injects a link via the exported activity; when user opens the article, it runs JS that can interact
  with in-app controls (annotations, TTS), potentially trick user or degrade UX.
  - Mitigation: Sanitize/strip scripts in fetched content; carefully scope addJavascriptInterface and turn off file access unless truly
  needed.

  5) “Origin URL” misuse (server-side UX/security)

  - What: Android passes origin_url into the server on add. If the server ever displays origin_url in UI without proper escaping, you can
  get UI/script injection or dangerous links (e.g., javascript:) presented to users/admins.
  - Low-effort check:
      - Add entry with origin_url set to a javascript: or odd scheme and see how the web UI renders it.
  - Mitigation: Strictly sanitize/validate origin_url on the server; disallow non-http(s) schemes; escape output.

  6) Known SSRF filter bypass patterns to test (no server code changes)

  - IPv6 literal (above): http://[::1]:PORT/…
  - IPv4 embedded forms: http://127.1/…, http://2130706433/…, http://0x7f000001/… (decimal/hex). Some filters miss these.
  - DNS CNAME chains to private IPs; ensure the SSRF layer resolves each hop and blocks if any resolution is private.
  - HTTP auth in URL: http://user:pass@host/ (shouldn’t bypass private detection, but verify behavior).
  - CRLF/Host smuggling: rare in PSR-18 clients but worth a negative test.

  How the two combine for real impact (without “changing settings”)

  - If the backend is left at defaults but:
      - IPv6 is available in the container/host network, or
      - Image caching is enabled (many admins turn this on), or
      - The SSRF layer is not used uniformly (images/OG fetches),
        then the Android “silent add” becomes a reliable pivot into backend SSRF without the victim’s awareness.
```