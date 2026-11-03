#!/usr/bin/env python3
"""
File watcher that triggers the agent pipeline when new files appear in /data/in.

Usage:
    python watch_and_process.py

Watches /data/in for bruto.txt files and runs:
1. Redator -> /data/out/limpo.txt
2. Triador -> /data/out/limpo.classificacao.json
3. Especialista (se ambíguo) -> /data/out/limpo.analise.json
4. Handoff -> /data/out/limpo.handoff.json
"""
import asyncio
import logging
import subprocess
import sys
import time
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

logging.basicConfig(
    level=logging.INFO,
    format='{"timestamp": "%(asctime)s", "level": "%(levelname)s", "watcher": "%(message)s"}'
)
logger = logging.getLogger("watcher")

IN_DIR = Path("/data/in")
OUT_DIR = Path("/data/out")
AGENTS_DIR = Path("/app")


class BrutoHandler(FileSystemEventHandler):
    """Handles new bruto.txt files."""

    def __init__(self):
        self.processing = set()

    def on_created(self, event):
        if event.is_directory:
            return

        path = Path(event.src_path)
        if path.name == "bruto.txt" and path not in self.processing:
            self.processing.add(path)
            asyncio.create_task(self.process_pipeline(path))

    async def process_pipeline(self, bruto_path: Path):
        """Runs the full pipeline for a bruto.txt file."""
        pipeline_id = bruto_path.stem  # or generate from content
        logger.info(f"Starting pipeline for {bruto_path}")

        try:
            # 1. Redator
            limpo_path = OUT_DIR / f"{pipeline_id}_limpo.txt"
            await self.run_agent("redator", [str(bruto_path), str(limpo_path)])

            # 2. Triador
            await self.run_agent("triador", [str(limpo_path)])

            # 3. Check if ambiguous -> Especialista
            classificacao_path = limpo_path.with_suffix(".classificacao.json")
            if classificacao_path.exists():
                import json
                with open(classificacao_path) as f:
                    classif = json.load(f)
                if classif.get("ambíguo"):
                    logger.info("Classification ambiguous, running especialista")
                    await self.run_agent("especialista", [str(classificacao_path)])

            # 4. Handoff
            await self.run_agent("handoff", [str(classificacao_path), "--canais", "slack"])

            logger.info(f"Pipeline completed for {bruto_path}")

        except Exception as e:
            logger.error(f"Pipeline failed for {bruto_path}: {e}")
        finally:
            self.processing.discard(bruto_path)

    async def run_agent(self, agent_name: str, args: list):
        """Runs an agent as subprocess."""
        cmd = [sys.executable, "-m", agent_name] + args
        logger.info(f"Running: {' '.join(cmd)}")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(AGENTS_DIR / agent_name),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.error(f"{agent_name} failed: {stderr.decode()}")
            raise RuntimeError(f"{agent_name} exited with {proc.returncode}")

        logger.info(f"{agent_name} completed: {stdout.decode().strip()}")


async def main():
    """Main watcher loop."""
    logger.info(f"Starting watcher on {IN_DIR}")

    IN_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    handler = BrutoHandler()
    observer = Observer()
    observer.schedule(handler, str(IN_DIR), recursive=False)
    observer.start()

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    asyncio.run(main())