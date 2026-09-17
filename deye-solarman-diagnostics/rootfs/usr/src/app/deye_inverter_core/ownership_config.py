"""Serialize local selection changes with the shared ownership registry."""
from __future__ import annotations

from pathlib import Path

from .ownership import EntityOwnership


class OwnershipCoordinator:
	def __init__(self, ownership: EntityOwnership, files, desired):
		self.ownership=ownership
		self.files={Path(path) for path in files}
		self.desired=desired

	def apply(self, action, strict=True):
		# All configuration writers use this same lock. Publication/write guards
		# cannot observe a partially updated local selection.
		with self.ownership.registry.locked():
			before={path:path.read_bytes() if path.exists() else None for path in self.files}
			try:
				result=action()
				self.ownership.reconcile(self.desired(),strict=strict)
				self.ownership.registry.commit_locked()
				return result
			except Exception:
				for path,content in before.items():
					if content is None:
						path.unlink(missing_ok=True)
					elif not path.exists() or path.read_bytes() != content:
						temporary=path.with_name(path.name+".ownership-rollback")
						temporary.write_bytes(content)
						temporary.replace(path)
				raise

	def reconcile(self):
		with self.ownership.registry.locked():
			return self.ownership.reconcile(self.desired())
