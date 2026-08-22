.PHONY: check clean commits site test validate

check: commits test validate site

commits:
	@if git rev-parse --verify HEAD >/dev/null 2>&1; then \
		python3 scripts/check_commit_messages.py HEAD; \
	else \
		echo "no commits yet; skipping history validation"; \
	fi

test:
	python3 -m unittest discover -s tests -v

validate:
	python3 scripts/release_tool.py validate --records-dir releases

site:
	python3 scripts/release_tool.py build-site \
		--records-dir releases \
		--static-dir site \
		--status status/nightly.json \
		--schema-dir schema \
		--output-dir _site

clean:
	rm -rf -- _site
