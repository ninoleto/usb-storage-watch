> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# Approved GUI to DEV9 API mapping

All drive-specific routes are bound to an explicit profile ID at `/api/drives/<profile>/<action>`. Global views do not inherit the previously managed drive. The server's existing browser authentication cookie and CSRF enforcement remain authoritative.

| Screen | Read API | Mutation API |
|---|---|---|
| Overview | `fleet-status` | `add-drive`, per-drive `monitor` |
| Manage Drive | per-drive `status`, `config` | per-drive `monitor`, `recovery-plan` → `recovery-settings`, `notification-settings`, `disk-operation` |
| Virtual Disk Images | per-drive `application-images`, `image-discover` | per-drive `image-plan` → `image-apply`, `image-action` |
| Docker & Applications | per-drive `config` | None in UI1; existing backend not modified |
| Prepare Drive | global `prepare-disks`, `prepare-progress` | global `prepare-drive-plan` → `prepare-drive` |
| Event History | global `fleet-events` | None |
| Email | global `global-config` | global `smtp`, `test-email` |
| Integrations (UI37) | authenticated network state, public CA and module download | existing management-token controls |
| Advanced | global `global-config`, `lan-info`, per-drive `config` | global `lan-auto`; per-drive `timing-settings` |

The approved UI visual hierarchy and screen separation have been retained. All source data is fetched after authentication. Unimplemented advanced functions are explicitly marked, not simulated.
