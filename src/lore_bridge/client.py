from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import requests


class BridgeError(Exception):
    pass


class BridgeClient:
    def __init__(self, base_url: str, api_key: str, *, timeout: float = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bearer {api_key}"

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def start_sync_from_portal(self, *, async_mode: bool = True) -> tuple[int, dict[str, Any]]:
        params = {"async": "true"} if async_mode else None
        return self._request_with_status("POST", "/sync/from-portal", params=params)

    def start_sync_from_dndbeyond(self, *, async_mode: bool = True) -> tuple[int, dict[str, Any]]:
        params = {"async": "true"} if async_mode else None
        return self._request_with_status("POST", "/sync/from-dndbeyond", params=params)

    def sync_from_dndbeyond(
        self,
        *,
        async_mode: bool = True,
        poll_interval: float = 2,
        on_update: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        return self._run_sync_action(
            "from-dndbeyond",
            self.start_sync_from_dndbeyond,
            async_mode=async_mode,
            poll_interval=poll_interval,
            on_update=on_update,
        )

    def start_publish_main(self, *, async_mode: bool = True) -> tuple[int, dict[str, Any]]:
        params = {"async": "true"} if async_mode else None
        return self._request_with_status("POST", "/sync/publish-main", params=params)

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self._request("GET", f"/sync/jobs/{job_id}")

    def get_current_job(self) -> dict[str, Any] | None:
        status, body = self._request_with_status("GET", "/sync/jobs/current")
        if status == 404:
            return None
        if status >= 400:
            raise BridgeError(f"GET /sync/jobs/current failed: {status} {body}")
        return body

    def pull_from_portal(
        self,
        *,
        async_mode: bool = True,
        poll_interval: float = 2,
        on_update: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        return self._run_sync_action(
            "from-portal",
            self.start_sync_from_portal,
            async_mode=async_mode,
            poll_interval=poll_interval,
            on_update=on_update,
        )

    def publish_main(
        self,
        *,
        async_mode: bool = True,
        poll_interval: float = 2,
        on_update: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        return self._run_sync_action(
            "publish-main",
            self.start_publish_main,
            async_mode=async_mode,
            poll_interval=poll_interval,
            on_update=on_update,
        )

    def _run_sync_action(
        self,
        label: str,
        starter: Callable[..., tuple[int, dict[str, Any]]],
        *,
        async_mode: bool,
        poll_interval: float,
        on_update: Callable[[dict[str, Any]], None] | None,
    ) -> dict[str, Any]:
        status, body = starter(async_mode=async_mode)
        if status == 409:
            current = self.get_current_job()
            if not current:
                raise BridgeError("Sync already in progress, but no active job was found.")
            job_id = current["job_id"]
        elif status == 202:
            job_id = body["job_id"]
        elif status == 200:
            return body
        else:
            raise BridgeError(f"POST /sync/{label} failed: {status} {body}")

        if not async_mode:
            return body

        return self.wait_for_job(job_id, poll_interval=poll_interval, on_update=on_update)

    def wait_for_job(
        self,
        job_id: str,
        *,
        poll_interval: float = 2,
        on_update: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        while True:
            try:
                job = self.get_job(job_id)
            except BridgeError as exc:
                raise BridgeError(
                    f"Lost sync job {job_id} (bridge restarted or job expired from memory). "
                    "The sync may not have finished — check bridge logs, then rerun."
                ) from exc

            if on_update:
                on_update(job)

            if job["status"] == "completed":
                return job
            if job["status"] == "failed":
                detail = job.get("message") or "sync job failed"
                raise BridgeError(detail)

            time.sleep(poll_interval)

    def _request(self, method: str, path: str, *, params: dict[str, str] | None = None) -> dict[str, Any]:
        status, body = self._request_with_status(method, path, params=params)
        if status >= 400:
            raise BridgeError(f"{method} {path} failed: {status} {body}")
        return body

    def _request_with_status(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        response = self._session.request(
            method,
            f"{self.base_url}{path}",
            params=params,
            timeout=self.timeout,
        )
        body: dict[str, Any]
        if response.text:
            try:
                body = response.json()
            except ValueError:
                body = {"detail": response.text[:1500]}
        else:
            body = {}
        return response.status_code, body
