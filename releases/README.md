# Release records

Add exactly one immutable `<release-id>.json` file for each published nightly. Generated index and
latest-pointer files do not belong here; `scripts/release_tool.py build-site` derives them into
`_site/releases/v1/`.

Before adding a record, publish and independently verify all referenced GitHub Release assets.
Then run `make check`.
