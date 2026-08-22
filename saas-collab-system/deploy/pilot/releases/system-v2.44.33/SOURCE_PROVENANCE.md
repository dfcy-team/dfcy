# V2.44.33 Git source provenance

This Git node records the source lineage and the immutable frontend artifact deployed as V2.44.33.

- Runtime artifact: `dist/` copied byte-for-byte from `system-v2.44.33-build-20260821`.
- Release manifest and notes: preserved from the deployed release audit.
- Backend/product source: verified against the SHA-256 allowlists in the V2.44.8–V2.44.33 manifests.
- Inherited development source: restored from the V2.44.31 release audit snapshot.
- Navigation: restored to the V2.44.32/V2.44.33 menu structure; post-release development-flow menu changes are excluded.
- Post-release migration `development.0007_v21_development_flow` and its frontend workflow changes are intentionally excluded.

The deployed `dist/` is the authoritative byte-for-byte frontend runtime record. Three inherited frontend source files (`router/menu.js`, `router/index.js`, and `DevelopmentProductArchiveList.vue`) were recovered from the release operation history because their original standalone source snapshot was not retained in the release archive; the immutable deployed chunks are included for final runtime comparison.
