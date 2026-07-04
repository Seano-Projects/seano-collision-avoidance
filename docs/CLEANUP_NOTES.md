# CLEANUP_NOTES.md — Ringkasan Cleanup Repo

Catatan hasil audit + cleanup repo yang sudah dilakukan, dan aturan singkat
untuk cleanup berikutnya jika file-file regenerable muncul lagi. Dokumen ini
tidak mengubah kode; murni referensi.

## 1. Ringkasan cleanup yang sudah dilakukan

Pada cleanup terakhir:

- `seano_ca_ws/evidence_phase7/` **dipindahkan** (bukan dihapus) ke:
  ```
  /home/seano/seano_repo_backups/repo_cleanup_20260704_181827/evidence_phase7
  ```
  Folder ini berisi evidence hasil pengujian (auto_runs, formal runs, arsip
  non-formal). Kalau butuh data itu lagi, ambil dari path backup di atas.
- Dihapus karena regenerable via `colcon build --symlink-install` atau murni
  cache/duplikat: `build/`, `install/`, `log/` (root & `seano_ca_ws/`),
  seluruh `__pycache__/`, dan `models/_export_artifacts/` (isinya duplikat
  identik — sudah diverifikasi MD5 — dari `models/yolov8n.pt` / `.onnx` /
  `.engine` yang asli).
- Dihapus karena sampah kecil tidak terpakai: 2 file `.bak_engine_*` milik
  `run_phase7_monitor_no_log.sh`, dan `seano_ca_ws/free_before.txt` yang
  nyasar di root workspace.

Semua langkah di atas dilakukan dengan approval eksplisit per-item, path
eksplisit (tanpa wildcard luas), dan diverifikasi dengan `colcon build` ulang
+ `compileall` setelahnya. Tidak ada commit yang dibuat dari proses ini.

## 2. Aman dihapus jika muncul lagi

File/folder berikut **regenerable** — aman dihapus kapan saja tanpa perlu
backup, karena akan otomatis dibuat ulang oleh `colcon build` atau oleh
Python saat runtime:

```
build/
install/
log/
__pycache__/
*.pyc
*.pyo
.pytest_cache
.mypy_cache
```

Semua sudah ada di `.gitignore` — tidak pernah tracked di git.

## 3. Jangan dihapus

```
seano_ca_ws/src/seano_vision/models/yolov8n.pt
seano_ca_ws/src/seano_vision/models/yolov8n.onnx
seano_ca_ws/src/seano_vision/models/yolov8n.engine
seano_ca_ws/src/seano_vision/seano_vision/*.py   (source code node)
seano_ca_ws/src/seano_vision/launch/*.py         (launch file)
seano_ca_ws/src/seano_vision/config/*.yaml       (config)
run_phase7_monitor_no_log.sh
run_pool_existing_control_path.sh
stop_phase7_safe.sh
PRD.md
AGENTS.md
SKILLS.md
README.md
seano_ca_ws/.last_*_dir
seano_ca_ws/.phase7_runtime/
.git/
```

Alasan singkat:
- **Model** (`.pt`/`.onnx`/`.engine`): `.onnx`/`.engine` gitignored tapi aktif
  dipakai runtime Jetson (TensorRT). Hapus berarti perlu export ulang yang
  lambat.
- **Source/launch/config/run-stop script**: safety-critical dan/atau
  operasional aktif — lihat [REPO_MAP.md](REPO_MAP.md) §5.
- **`.last_*_dir`, `.phase7_runtime/`**: state runtime yang dipakai
  `run_phase7_monitor_no_log.sh` / `stop_phase7_safe.sh` untuk melacak sesi
  aktif — masih berstatus "tunggu konfirmasi user" dari audit sebelumnya,
  belum di-approve untuk dihapus.
- **`.git/`**: histori version control, di luar cakupan cleanup file kerja.

## 4. `build/`, `install/`, `log/` boleh muncul lagi — itu normal

Setiap kali menjalankan `colcon build --symlink-install` (baik manual, maupun
lewat langkah rebuild sesudah cleanup), ROS2/colcon akan membuat ulang
`build/`, `install/`, `log/` di root maupun di dalam `seano_ca_ws/`. Ini
**bukan tanda repo kotor lagi** — ini output build yang memang gitignored dan
regenerable, dan repo memang perlu folder ini ada supaya `source
install/setup.bash` berfungsi saat runtime. Cleanup ulang terhadap folder ini
aman dilakukan kapan saja mengikuti daftar §2, tapi tidak wajib — folder ini
tidak mengganggu kejelasan struktur repo karena sudah dipisahkan jelas oleh
`.gitignore` dan oleh [REPO_MAP.md](REPO_MAP.md).
