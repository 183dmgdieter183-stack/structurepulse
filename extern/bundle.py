"""
StructurePulse — Meta-Library Bundle
Portable, self-contained package of library entries and patterns.
Used as the stable exchange format between repos and peers.

Bundle structure (tar.gz):
  manifest.json       — metadata, signature, content hashes
  entries/            — library entry JSON files
  modules/            — source code for each entry
  patterns/           — user-defined pattern JSON files

Trust model:
  - SHI gate: only entries above threshold are included
  - SHA-256 hash per file, Merkle root in manifest
  - Receiver validates hashes before importing
  - Receiver applies own SHI threshold — can be stricter than sender
"""
import json
import hashlib
import tarfile
import tempfile
import shutil
import io
from pathlib import Path
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional


BUNDLE_VERSION = "1"
MANIFEST_FILE  = "manifest.json"
ENTRIES_DIR    = "entries"
MODULES_DIR    = "modules"
PATTERNS_DIR   = "patterns"


@dataclass
class BundleEntry:
    """Lightweight representation of a library entry in a bundle."""
    id: str
    name: str
    description: str
    language: str
    shi: float
    fd: float
    status: str
    tags: list
    fingerprint: dict
    module_file: str          # relative path inside bundle
    source_hash: str          # SHA-256 of module source


@dataclass
class BundleManifest:
    version: str = BUNDLE_VERSION
    created_at: str = ""
    source_repo: str = ""      # fingerprint of origin repo
    entry_count: int = 0
    pattern_count: int = 0
    shi_threshold: float = 0.0
    merkle_root: str = ""      # hash of all file hashes
    entries: list = field(default_factory=list)   # list of BundleEntry dicts
    patterns: list = field(default_factory=list)  # pattern ids
    tags_index: dict = field(default_factory=dict)  # tag → [entry_ids]


class BundleBuilder:
    """Builds a portable bundle from a local library."""

    def build(self,
              library,
              output_path: str,
              shi_threshold: float = 0.65,
              tags: list = None,
              language: str = None,
              repo_fingerprint: str = "") -> "BundleManifest":
        """
        Pack library entries into a .sptgz bundle file.
        Only entries above shi_threshold are included.
        """
        # filter entries
        entries = library.search(
            min_shi=shi_threshold,
            language=language,
            limit=500,
        )
        if tags:
            entries = [e for e in entries if any(t in e.tags for t in tags)]

        tmpdir = Path(tempfile.mkdtemp(prefix="sp_bundle_"))
        try:
            (tmpdir / ENTRIES_DIR).mkdir()
            (tmpdir / MODULES_DIR).mkdir()
            (tmpdir / PATTERNS_DIR).mkdir()

            bundle_entries = []
            file_hashes = {}

            for entry in entries:
                src = Path(entry.stored_path)
                if not src.exists():
                    continue

                # copy module source
                dest_name = f"{entry.id}_{src.name}"
                dest = tmpdir / MODULES_DIR / dest_name
                if src.is_file():
                    shutil.copy2(src, dest)
                elif src.is_dir():
                    shutil.copytree(src, dest,
                                    ignore=shutil.ignore_patterns(
                                        ".structurepulse", ".git", "__pycache__"))

                # hash
                src_hash = self._hash_path(dest)
                file_hashes[str(dest.relative_to(tmpdir))] = src_hash

                # write entry JSON
                be = BundleEntry(
                    id=entry.id,
                    name=entry.name,
                    description=entry.description,
                    language=entry.language,
                    shi=entry.shi,
                    fd=entry.fd,
                    status=entry.status,
                    tags=entry.tags,
                    fingerprint=asdict(entry.fingerprint) if entry.fingerprint else {},
                    module_file=f"{MODULES_DIR}/{dest_name}",
                    source_hash=src_hash,
                )
                bundle_entries.append(be)
                entry_path = tmpdir / ENTRIES_DIR / f"{entry.id}.json"
                entry_path.write_text(json.dumps(asdict(be), indent=2), encoding="utf-8")
                file_hashes[str(entry_path.relative_to(tmpdir))] = self._hash_file(entry_path)

            # tags index
            tags_index = {}
            for be in bundle_entries:
                for tag in be.tags:
                    tags_index.setdefault(tag, []).append(be.id)

            # merkle root
            merkle_root = self._merkle(file_hashes)

            manifest = BundleManifest(
                created_at=datetime.now(timezone.utc).isoformat(),
                source_repo=repo_fingerprint,
                entry_count=len(bundle_entries),
                shi_threshold=shi_threshold,
                merkle_root=merkle_root,
                entries=[asdict(be) for be in bundle_entries],
                tags_index=tags_index,
            )

            manifest_path = tmpdir / MANIFEST_FILE
            manifest_path.write_text(json.dumps(asdict(manifest), indent=2), encoding="utf-8")

            # pack into tar.gz
            out = Path(output_path)
            with tarfile.open(out, "w:gz") as tar:
                for f in sorted(tmpdir.rglob("*")):
                    if f.is_file():
                        tar.add(f, arcname=str(f.relative_to(tmpdir)))

            return manifest

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def _hash_file(self, path: Path) -> str:
        h = hashlib.sha256()
        h.update(path.read_bytes())
        return h.hexdigest()

    def _hash_path(self, path: Path) -> str:
        """Hash file or directory (sorted recursive)."""
        if path.is_file():
            return self._hash_file(path)
        h = hashlib.sha256()
        for f in sorted(path.rglob("*")):
            if f.is_file():
                h.update(f.read_bytes())
        return h.hexdigest()

    def _merkle(self, file_hashes: dict) -> str:
        combined = "".join(v for _, v in sorted(file_hashes.items()))
        return hashlib.sha256(combined.encode()).hexdigest()


class BundleReader:
    """Reads and validates a bundle, then imports into a local library."""

    def read_manifest(self, bundle_path: str) -> BundleManifest:
        with tarfile.open(bundle_path, "r:gz") as tar:
            manifest_member = tar.getmember(MANIFEST_FILE)
            f = tar.extractfile(manifest_member)
            data = json.loads(f.read().decode("utf-8"))
            return BundleManifest(**data)

    def validate(self, bundle_path: str) -> dict:
        """Verify all file hashes match manifest."""
        errors = []
        warnings = []

        try:
            manifest = self.read_manifest(bundle_path)
        except Exception as e:
            return {"valid": False, "errors": [f"Cannot read manifest: {e}"]}

        with tarfile.open(bundle_path, "r:gz") as tar:
            for be_dict in manifest.entries:
                be = BundleEntry(**be_dict)
                try:
                    member = tar.getmember(be.module_file)
                    f = tar.extractfile(member)
                    if f:
                        content = f.read()
                        actual_hash = hashlib.sha256(content).hexdigest()
                        if actual_hash != be.source_hash:
                            errors.append(f"Hash mismatch: {be.id} ({be.name})")
                except KeyError:
                    warnings.append(f"Module file missing: {be.module_file} for {be.id}")

        return {
            "valid": len(errors) == 0,
            "entry_count": manifest.entry_count,
            "shi_threshold": manifest.shi_threshold,
            "source_repo": manifest.source_repo,
            "created_at": manifest.created_at,
            "errors": errors,
            "warnings": warnings,
        }

    def import_into(self, bundle_path: str,
                    library,
                    min_shi: float = 0.0,
                    tags_filter: list = None,
                    dry_run: bool = False) -> dict:
        """
        Extract bundle and import entries into local library.
        Returns import report.
        """
        validation = self.validate(bundle_path)
        if not validation["valid"]:
            return {"success": False, "errors": validation["errors"]}

        manifest = self.read_manifest(bundle_path)
        imported = []
        skipped = []

        tmpdir = Path(tempfile.mkdtemp(prefix="sp_import_"))
        try:
            with tarfile.open(bundle_path, "r:gz") as tar:
                tar.extractall(tmpdir,
                               filter="data")  # safe extraction

            for be_dict in manifest.entries:
                be = BundleEntry(**be_dict)

                # apply filters
                if be.shi < min_shi:
                    skipped.append({"id": be.id, "name": be.name,
                                    "reason": f"SHI {be.shi} below threshold {min_shi}"})
                    continue
                if tags_filter and not any(t in be.tags for t in tags_filter):
                    skipped.append({"id": be.id, "name": be.name,
                                    "reason": "no matching tags"})
                    continue

                if dry_run:
                    imported.append({"id": be.id, "name": be.name,
                                     "shi": be.shi, "action": "would import"})
                    continue

                # check if already exists by name
                existing = library.search(query=be.name, limit=1)
                if existing and existing[0].name == be.name:
                    skipped.append({"id": be.id, "name": be.name,
                                    "reason": f"already in library as {existing[0].id}"})
                    continue

                # copy module to a temp location library can read
                module_src = tmpdir / be.module_file
                if not module_src.exists():
                    skipped.append({"id": be.id, "name": be.name,
                                    "reason": "module file not found in bundle"})
                    continue

                entry = library.add(
                    source_path=str(module_src),
                    name=be.name,
                    description=be.description,
                    tags=be.tags,
                )
                # preserve structural metrics from bundle — no re-scan needed
                entries_all = library.read_all()
                for e in entries_all:
                    if e.id == entry.id:
                        e.shi = be.shi
                        e.fd  = be.fd
                        e.status = be.status
                library._rewrite_index(entries_all)
                imported.append({"id": entry.id, "name": entry.name,
                                  "shi": be.shi, "original_id": be.id})

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        return {
            "success": True,
            "dry_run": dry_run,
            "imported": 0 if dry_run else len(imported),
            "would_import": len(imported) if dry_run else 0,
            "skipped": len(skipped),
            "details": {"imported": imported, "skipped": skipped},
        }
