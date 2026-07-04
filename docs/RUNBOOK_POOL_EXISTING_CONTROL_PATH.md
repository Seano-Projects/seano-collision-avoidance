# RUNBOOK — Pool Test dengan Jalur Kontrol Eksisting (`/usv/thruster`)

Dokumen ini murni prosedur/dokumentasi. Tidak ada kode yang dijalankan atau
diubah untuk membuat dokumen ini.

## 1. Tujuan pengujian

Menguji pipeline collision avoidance (deteksi → risk evaluation → command
internal → logging KTI) di kolam **tanpa mengambil alih aktuasi fisik**.
Aktuasi tetap sepenuhnya melalui jalur kontrol SEANO yang sudah berjalan
(`/usv/thruster` rekan → `/mavros/rc/override`). Repo collision avoidance ini
hanya mengamati dan mencatat, tidak mengendalikan thruster.

## 2. Batasan jalur kontrol (wajib dipahami sebelum uji)

- **`/usv/thruster` (punya rekan) tetap menjadi satu-satunya publisher ke
  `/mavros/rc/override`.** Repo ini tidak boleh dan tidak akan menjadi
  publisher kedua di topik itu pada skema ini.
- Repo collision avoidance **tidak menjalankan `mavros_rc_override_bridge_node`**
  pada skema ini (`use_rc_override_bridge:=false` di launch argumen). Node
  yang biasanya menjadi satu-satunya jalur repo ini untuk publish RC override
  sengaja tidak diaktifkan.
- Repo ini juga **tidak menjalankan instance MAVROS baru** (`use_mavros:=false`)
  — MAVROS yang dipakai adalah `mavros.service` milik sistem/rekan yang sudah
  berjalan.
- Script ini **tidak mengoverride `ca_runtime_profile`**, sehingga memakai
  default launch file, yaitu profile **`usb_watchdog`** (profile
  default/current) — **bukan** profile `full`. Konsekuensinya, lima node
  perception/safety opsional (`vision_quality_node`, `false_positive_guard_node`,
  `frame_freeze_detector_node`, `multi_target_fusion_node`,
  `waterline_horizon_node`) **tidak ikut berjalan** pada skema ini. Detail node
  mana yang aktif vs optional ada di
  [REPO_MAP.md](REPO_MAP.md) §4–§5.

## 3. Command utama

```bash
cd ~/resource_git/seano-collision-avoidance2/seano_ca_ws
./run_pool_existing_control_path.sh
```

Script ini melakukan preflight read-only dulu (lihat §5), baru menjalankan
`ros2 launch phase7_cuav_usb_hardware.launch.py` di foreground dengan
argumen yang memastikan batasan §2 di atas.

## 4. Cara stop

**Ctrl+C** di terminal yang menjalankan script.

Script berjalan di foreground (bukan background/`setsid`), jadi Ctrl+C
langsung mengirim sinyal stop ke seluruh node yang di-launch — tidak perlu
menjalankan script stop terpisah, dan **tidak menyentuh** `/usv/thruster`,
`seano.service`, atau `mavros.service`.

## 5. Preflight (dilakukan otomatis oleh script sebelum launch)

Script mengecek hal berikut sebelum benar-benar menjalankan pipeline:

| Cek | Syarat aman |
|---|---|
| `connected` (status FCU di `/mavros/state`) | `true` |
| `mode` (mode terbang/kendali di `/mavros/state`) | **bukan** `RTL` |
| `armed` | sesuai prosedur operator (di luar cakupan script — cek manual sebelum start) |
| Publisher `/mavros/rc/override` | hanya `/usv/thruster` |
| `mavros_rc_override_bridge_node` | belum berjalan sama sekali |
| `ca_mode` (setelah pipeline jalan) | `NORMAL` atau `CAUTION` — kalau `LOST_PERCEPTION`, cek kualitas gambar/kamera |
| Event logger | aktif (`use_event_logger:=true`, terlihat dari log run_id di terminal) |

Catatan: pengecekan `armed` tidak otomatis di dalam script (script ini tidak
mengubah/membaca status arm secara langsung) — pastikan status arm sesuai
prosedur operator Anda sebelum menjalankan script.

Catatan `ca_mode`/`LOST_PERCEPTION`: pada skema ini, mode `LOST_PERCEPTION`
dan failsafe kualitas kamera dihasilkan oleh **`risk_evaluator_node.py`**
(vision-quality dihitung internal di dalam node itu sendiri) dan
**`watchdog_failsafe_node.py`** (staleness check image/risk/mode) — **bukan**
oleh node `vision_quality_node.py` eksternal, karena node itu bagian dari
profile `full` dan tidak berjalan di sini (lihat [REPO_MAP.md](REPO_MAP.md) §5).
Jadi kalau `ca_mode=LOST_PERCEPTION` muncul, penyebabnya ada di kualitas
gambar/staleness yang dibaca langsung oleh kedua node itu, bukan indikasi
node eksternal yang mati.

## 6. Kriteria abort

Script akan **berhenti sebelum launch** (tidak lanjut ke `ros2 launch`) jika:

- `mavros_rc_override_bridge_node` sudah terdeteksi berjalan di ROS graph.
- Tidak ada publisher sama sekali di `/mavros/rc/override` (berarti
  `/usv/thruster` belum aktif — tidak ada gunanya menjalankan CA tanpa jalur
  aktuasi).
- Ada publisher lain selain `/usv/thruster` di `/mavros/rc/override` (abort
  langsung, tanpa prompt konfirmasi — indikasi ada sumber RC override ganda).
- `/mavros/state` menunjukkan mode `RTL`, **atau** `/mavros/state` tidak bisa
  dibaca sama sekali — pada dua kasus ini script akan menampilkan warning dan
  meminta konfirmasi manual (`yes`) sebelum lanjut; kalau tidak dikonfirmasi,
  script berhenti.

Kalau abort terjadi, tidak ada node yang sempat dijalankan oleh script ini —
aman untuk memperbaiki kondisi dan menjalankan ulang.

## 7. File log yang dicek setelah uji

Semua ditulis oleh `event_logger_node` ke:

```
~/seano_event_logs/<RUN_ID>/
```

dengan `<RUN_ID>` seperti `POOL_EXISTING_CONTROL_PATH_<timestamp>` yang
ditampilkan script saat start (`LOG_DIR` di output). Isi folder itu:

- `time_series.csv` — deret waktu metrik per siklus (risk, command, dsb).
- `avoidance_cycles.csv` — ringkasan per siklus avoidance (mulai/selesai, durasi, hasil).
- `metrics_summary.csv` — ringkasan metrik akhir run, format CSV.
- `metrics_summary.json` — ringkasan metrik akhir run, format JSON.
- `events.csv` — log event diskrit (perubahan mode, command_safe, dsb), format CSV.
- `events.jsonl` — log event diskrit yang sama, format JSON Lines.

Selain itu, stdout mentah run disimpan terpisah di `/tmp/<RUN_ID>_stdout.txt`
(ditampilkan juga sebagai `STDOUT` oleh script saat start).

## 8. Catatan KTI

Sistem collision avoidance pada skema ini menghasilkan **deteksi objek, risk
score, dan command internal**, serta mencatatnya lewat event logger — semua
itu adalah data yang diukur untuk KTI. **Aktuasi fisik kapal tetap berjalan
sepenuhnya melalui jalur kontrol eksisting SEANO** (`/usv/thruster`), bukan
lewat command internal CA. Artinya data KTI dari skema ini mengukur kualitas
pipeline deteksi/keputusan CA secara independen dari aktuasi — bukan hasil
akhir manuver kapal yang benar-benar dieksekusi oleh CA.
