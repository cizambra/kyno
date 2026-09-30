# Maintaining the Kyno website

GitHub Pages serves the committed `site/` directory. Changes under `site/`
deploy automatically after they merge into `main` through
`.github/workflows/pages.yml`.

## Preview before merging

From the repository root:

```bash
python -m http.server --directory site 8000
```

Open `http://localhost:8000/`. Check desktop and mobile widths, keyboard
navigation, both copy buttons, pause/resume, and reduced-motion behavior.
The canonical URLs deliberately identify the public website.

The constitution page is generated from `constitution.yaml` and
`site-src/constitution.html`. Preserve its ledger version and date when
rebuilding; see `build-constitution.py` for the command.

## Search discovery after deployment

1. Verify the URL-prefix property `https://cizambra.github.io/kyno/` in
   [Google Search Console](https://search.google.com/search-console/).
   Follow its ownership-verification instructions; keep verification files
   or metadata committed if that method requires them.
2. Submit `https://cizambra.github.io/kyno/sitemap.xml` through the Sitemaps
   report. Check that both listed pages return HTTP 200 and identify the
   same URLs with their canonical links.
3. Inspect the homepage with URL Inspection and request indexing. Check the
   indexing report after Google has crawled the pages. Submission does not
   guarantee indexing or rankings.

The site is hosted under `/kyno/`. Crawlers read `robots.txt` only from the
host root, `https://cizambra.github.io/robots.txt`; putting one in this
project's `site/` directory would not control crawling. Any host-wide rules
belong to that root website.

When adding a public HTML page, add its canonical URL to `site/sitemap.xml`.
Do not include JSON exports, assets, fragment URLs, or duplicate `index.html`
URLs. If the public hostname changes, update canonicals, the sitemap, and
social metadata together. Keep the constitution's canonical URL in its
source template as well as its generated output.

The homepage includes `SoftwareSourceCode` metadata identifying the actual
repository, package, runtime, version, and licensing overview. Keep it
consistent with the visible release content. Share previews use
`site/assets/social-preview.png`.

References: [Google's sitemap guide](https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap),
[requesting a recrawl](https://developers.google.com/search/docs/crawling-indexing/ask-google-to-recrawl),
and [robots.txt location rules](https://developers.google.com/crawling/docs/robots-txt/create-robots-txt).
