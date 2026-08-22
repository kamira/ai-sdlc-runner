## Purpose

When one requirement/change spans multiple git repos (frontend + backend + shared lib, microservices…), governance docs are scattered across repos, and three problems are common: **contract mismatch** (one side changed the API, the other didn't follow), **"which repo is the source of truth?"**, and **half-done changes** (changed repo A, forgot repo B). This file defines a single cross-repo source of truth, coordinated changes, and consistency checks. **It happens solo (several of your own repos) or in a team.**

