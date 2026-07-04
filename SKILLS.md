# SKILLS.md

# Claude Code Skills for SEANO Collision Avoidance

## 1. Purpose

File ini berisi workflow kerja yang harus digunakan Claude Code saat membantu audit, pengecekan, atau perbaikan kecil pada repo `seano-collision-avoidance2`.

Repo ini berisi sistem collision avoidance USV SEANO yang sudah berjalan pada hardware. Sistem sudah dapat digunakan saat USV berada pada mode AUTO dan menjalankan mission, kemudian mendeteksi obstacle, menghitung risk score, dan memberi respons penghindaran seperti SLOW_DOWN, STOP, atau belok.

Gunakan file ini sebagai panduan skill praktis. Untuk aturan keselamatan dan batas repo, selalu ikuti `AGENTS.md`. Untuk kebutuhan sistem dan data KTI, selalu ikuti `PRD.md`.

## 2. Skill 1: Project Orientation

Gunakan skill ini pada awal sesi atau saat belum yakin dengan struktur repo.

Tujuan:

1. Memastikan Claude Code berada di repo yang benar.
2. Memahami struktur workspace.
3. Menentukan launch file, node, config, script run, script stop, dan logger yang relevan.
4. Menghindari salah edit repo rekan lain.

Langkah kerja:

1. Cek lokasi kerja.

```bash
pwd
ls -la
git rev-parse --show-toplevel
```

2. Pastikan root repo adalah `seano-collision-avoidance2`.

3. Baca dokumen utama.

```bash
cat PRD.md
cat AGENTS.md
cat SKILLS.md
```

4. Petakan struktur repo secara read-only.

```bash
find . -maxdepth 3 -type f | sort
```

5. Cari file penting.

```bash
find . -type f \( -name "*.py" -o -name "*.launch.py" -o -name "*.yaml" -o -name "*.sh" -o -name "*.md" \) | sort
```

6. Jangan edit apa pun pada tahap orientasi.

Output yang harus diberikan:

1. Root repo yang terdeteksi.
2. Workspace ROS 2 yang digunakan.
3. Package utama.
4. Launch file utama.
5. Node utama.
6. Script run dan stop.
7. File logger.
8. Potensi risiko awal jika ada.

## 3. Skill 2: Safe Static Audit

Gunakan skill ini untuk mengecek program tanpa menjalankan hardware.

Tujuan:

1. Mengecek konsistensi file program.
2. Mengecek hubungan launch argument dan parameter node.
3. Mengecek publisher dan subscriber.
4. Mengecek alur kamera sampai aktuasi.
5. Mengecek apakah logger sudah mendukung data KTI.

Langkah kerja:

1. Baca launch file hardware dan launch file test yang relevan.

```bash
find . -name "*.launch.py" | sort
```

2. Cari semua parameter node.

```bash
rg "declare_parameter|get_parameter|LaunchConfiguration|DeclareLaunchArgument" .
```

3. Cocokkan launch argument dengan parameter yang benar-benar dibaca node.

4. Cari topic publisher dan subscriber.

```bash
rg "create_publisher|create_subscription|Publisher|Subscriber" seano_ca_ws/src
```

5. Petakan alur topic dari kamera sampai aktuator.

6. Cek apakah node berikut ada dan konsisten:

1. camera node.
2. detector node.
3. risk evaluator node.
4. watchdog atau failsafe node.
5. mission mode manager.
6. command mux.
7. actuator safety limiter.
8. MAVROS atau RC override bridge.
9. event atau metrics logger.

7. Jangan patch terlebih dahulu. Buat laporan audit.

Checklist audit:

1. Tidak ada parameter launch yang tidak dipakai tanpa alasan.
2. Tidak ada parameter node yang tidak bisa dikonfigurasi dari launch jika penting.
3. Tidak ada topic mismatch.
4. Tidak ada command yang melewati safety layer.
5. Tidak ada direct actuator output yang bypass limiter.
6. Tidak ada logger yang membebani runtime tanpa kebutuhan.
7. Tidak ada penggunaan snapshot gambar sebagai default utama.
8. Tidak ada istilah `override_blocked` sebagai status utama yang ambigu.

Output yang harus diberikan:

1. File yang diperiksa.
2. Alur node dan topic.
3. Mismatch yang ditemukan.
4. Risiko terhadap safety.
5. Risiko terhadap data KTI.
6. Rekomendasi patch kecil jika perlu.

## 4. Skill 3: Static Check and Build Check

Gunakan skill ini setelah audit atau setelah patch kecil.

Tujuan:

1. Memastikan Python tidak error compile.
2. Memastikan package ROS 2 masih bisa build.
3. Memastikan perubahan tidak merusak workspace repo ini.

Aturan penting:

1. Jalankan hanya di workspace repo ini.
2. Jangan build workspace rekan lain.
3. Jangan hapus `build`, `install`, atau `log` tanpa izin.
4. Jangan jalankan `colcon clean` tanpa izin.
5. Jangan install dependency system tanpa izin.

Static check Python:

```bash
python3 -m compileall -q seano_ca_ws/src/seano_vision/seano_vision
```

Build check:

```bash
source /opt/ros/humble/setup.bash
cd seano_ca_ws
colcon build --symlink-install
```

Setelah build:

```bash
source install/setup.bash
ros2 pkg list | grep seano
ros2 pkg executables seano_vision
```

Jika gagal:

1. Jangan refactor besar.
2. Laporkan error spesifik.
3. Tunjukkan file dan baris yang bermasalah.
4. Beri patch kecil jika aman.
5. Ulangi compile check setelah patch.

Output yang harus diberikan:

1. Perintah yang dijalankan.
2. Hasil compile.
3. Hasil build.
4. Error jika ada.
5. File yang perlu diperbaiki.
6. Status aman atau belum aman untuk runtime check.

## 5. Skill 4: ROS 2 Runtime Observation

Gunakan skill ini hanya jika user mengizinkan pengecekan runtime.

Tujuan:

1. Mengamati node dan topic yang aktif.
2. Mengecek apakah data mengalir.
3. Mengecek kamera, detector, risk, command, safety, dan aktuasi tanpa mengubah sistem.
4. Menghindari gangguan pada repo atau proses rekan lain.

Aturan sebelum runtime:

1. Pastikan operator siap.
2. Pastikan USV diawasi.
3. Pastikan area aman.
4. Pastikan stop script tersedia.
5. Jangan menjalankan hardware launch tanpa izin.
6. Jangan menjalankan dua bridge aktuasi.
7. Jangan menjalankan dua MAVROS pada jalur yang sama.
8. Jangan kill proses global.

Perintah observasi read-only:

```bash
source /opt/ros/humble/setup.bash
source seano_ca_ws/install/setup.bash
ros2 node list
ros2 topic list
```

Cek topic satu kali:

```bash
ros2 topic echo /ca/risk --once
ros2 topic echo /ca/command --once
ros2 topic echo /ca/metrics --once
ros2 topic echo /ca/failsafe_active --once
```

Cek topic info:

```bash
ros2 topic info /ca/risk
ros2 topic info /ca/command
ros2 topic info /ca/metrics
```

Jangan echo raw image terus-menerus kecuali diperlukan. Raw image dapat membebani terminal dan runtime.

Runtime checklist:

1. Kamera publish citra.
2. Detector publish detection.
3. Risk evaluator publish risk score.
4. Risk evaluator publish metrics JSON.
5. Command publish sesuai risk.
6. Failsafe status tersedia.
7. Takeover status tersedia.
8. Actuator output tersedia.
9. Manual authority status tersedia.
10. Tidak ada node crash.

Output yang harus diberikan:

1. Node aktif.
2. Topic aktif.
3. Topic yang tidak muncul.
4. Data yang terlihat normal.
5. Data yang tidak konsisten.
6. Risiko jika runtime dilanjutkan.
7. Perlu patch atau tidak.

## 6. Skill 5: Metrics and KTI Evidence Audit

Gunakan skill ini untuk mengecek apakah data hasil pengujian cukup untuk KTI.

Tujuan:

1. Memastikan log berisi data numerik yang dapat diolah.
2. Memastikan lima faktor risiko visual tercatat.
3. Memastikan waktu respons dapat dihitung.
4. Memastikan command, risk, takeover, failsafe, dan aktuasi tercatat.
5. Mengurangi ketergantungan pada snapshot gambar.

File evidence yang dicari:

1. `scenario_info.csv`.
2. `terminal_log.txt`.
3. `time_series.csv`.
4. `avoidance_cycles.csv`.
5. `metrics_summary.csv`.
6. `metrics_summary.json`.
7. `events.csv`.
8. `events.jsonl`.
9. `tegrastats_raw.txt`.

Perintah audit evidence:

```bash
find . -type f \( -name "time_series.csv" -o -name "avoidance_cycles.csv" -o -name "metrics_summary.csv" -o -name "metrics_summary.json" -o -name "events.csv" -o -name "events.jsonl" \) | sort
```

Cek header CSV:

```bash
python3 - <<'PY'
import csv
from pathlib import Path

for p in sorted(Path(".").rglob("*.csv")):
    if p.name in {"time_series.csv", "avoidance_cycles.csv", "metrics_summary.csv", "events.csv"}:
        try:
            with p.open(newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader, [])
            print("\n" + str(p))
            print(header)
        except Exception as e:
            print(f"{p}: ERROR {e}")
PY
```

Lima faktor risiko yang wajib ada atau dapat diekstrak:

1. `proximity`.
2. `centrality`.
3. `approach`.
4. `bearing_consistency`.
5. `vttc_score`.

Nama internal yang dapat diterima:

1. `components.prox`.
2. `components.center`.
3. `components.approach`.
4. `components.bconst`.
5. `components.ttc_score`.

Waktu respons yang wajib dicek:

1. `first_detection_time_sec`.
2. `first_risk_time_sec`.
3. `first_hazard_command_time_sec`.
4. `takeover_start_time_sec`.
5. `auto_enable_time_sec`.
6. `rc_override_enable_time_sec`.
7. `first_actuator_output_time_sec`.
8. `avoid_start_time_sec`.
9. `rejoin_start_time_sec`.
10. `mission_return_time_sec`.
11. `cycle_end_time_sec`.

Durasi yang perlu ada atau dapat dihitung:

1. `detection_to_risk_s`.
2. `risk_to_command_s`.
3. `command_to_takeover_s`.
4. `command_to_auto_enable_s`.
5. `command_to_rc_override_s`.
6. `command_to_actuator_s`.
7. `detection_to_actuator_s`.
8. `avoid_duration_s`.
9. `total_avoidance_cycle_s`.

Data aktuasi yang wajib dicek:

1. `auto_left_cmd`.
2. `auto_right_cmd`.
3. `selected_left_cmd`.
4. `selected_right_cmd`.
5. `final_left_cmd`.
6. `final_right_cmd`.
7. `manual_left_cmd`.
8. `manual_right_cmd`.
9. `max_abs_left_cmd`.
10. `max_abs_right_cmd`.
11. `max_abs_diff_cmd`.

Output audit KTI:

1. File evidence yang ditemukan.
2. Kolom yang sudah cukup.
3. Kolom yang belum tersedia.
4. Data yang bisa langsung dipakai untuk tabel.
5. Data yang bisa langsung dipakai untuk grafik.
6. Patch logger yang disarankan jika perlu.

## 7. Skill 6: Logger Improvement Workflow

Gunakan skill ini jika user meminta perbaikan logger.

Tujuan:

1. Membuat logger fokus pada metrik KTI.
2. Memastikan snapshot tidak aktif default.
3. Memastikan image subscription tidak berjalan jika tidak perlu.
4. Menambahkan kolom penting tanpa mengubah logic risk atau safety.

Aturan patch logger:

1. Jangan ubah risk evaluator logic jika targetnya hanya logging.
2. Jangan ubah command decision jika targetnya hanya logging.
3. Jangan ubah safety threshold.
4. Jangan ubah actuator mapping.
5. Tambahkan kolom secara backward-compatible jika memungkinkan.
6. Jangan hapus file output lama kecuali user meminta.
7. Jangan membuat logger terlalu berat.

Patch yang disarankan:

1. Set `save_frames=false` sebagai default.
2. Jangan subscribe image jika `save_frames=false`.
3. Tambahkan lima faktor risiko ke `time_series.csv`.
4. Tambahkan timestamp response ke `avoidance_cycles.csv`.
5. Tambahkan distribusi risk class ke `metrics_summary`.
6. Tambahkan distribusi command ke `metrics_summary`.
7. Tambahkan aktuasi kiri-kanan ke `time_series.csv`.
8. Tambahkan status takeover, release, failsafe, manual authority.
9. Simpan detail `override_blocked` hanya sebagai diagnostic internal, bukan status utama.

Verifikasi setelah patch logger:

```bash
python3 -m compileall -q seano_ca_ws/src/seano_vision/seano_vision
```

Jika memungkinkan, jalankan test non-hardware atau dry-run yang tidak menggerakkan aktuator.

Output setelah patch logger:

1. Kolom baru yang ditambahkan.
2. File output yang terdampak.
3. Perubahan default snapshot.
4. Dampak runtime.
5. Cara mengecek hasil log setelah pengujian.

## 8. Skill 7: Minimal Patch Workflow

Gunakan skill ini jika masalah sudah jelas dan patch memang diperlukan.

Tujuan:

1. Memperbaiki masalah dengan perubahan sekecil mungkin.
2. Menjaga safety-critical logic tetap aman.
3. Menjaga build tetap berhasil.
4. Menjaga data KTI tetap lengkap.

Langkah kerja:

1. Jelaskan masalah.
2. Tunjukkan file yang bermasalah.
3. Jelaskan patch yang akan dilakukan.
4. Pastikan patch tidak menyentuh safety-critical logic.
5. Edit file seminimal mungkin.
6. Jalankan static check.
7. Tampilkan diff.
8. Laporkan dampak.

Perintah untuk melihat diff:

```bash
git diff --stat
git diff
```

Checklist sebelum patch:

1. Apakah patch menyentuh MAVROS?
2. Apakah patch menyentuh RC override?
3. Apakah patch menyentuh PWM?
4. Apakah patch menyentuh mapping left/right?
5. Apakah patch menyentuh threshold risk?
6. Apakah patch menyentuh STOP logic?
7. Apakah patch menyentuh failsafe?
8. Apakah patch menyentuh manual authority?
9. Apakah patch menyentuh repo lain?

Jika jawaban salah satu poin di atas adalah ya, berhenti dan minta izin user.

Output setelah patch:

1. File yang diubah.
2. Ringkasan perubahan.
3. Alasan perubahan.
4. Dampak terhadap safety.
5. Dampak terhadap data KTI.
6. Check yang berhasil.
7. Check yang belum dijalankan.
8. Rekomendasi pengujian berikutnya.

## 9. Skill 8: Terminal and HUD Text Cleanup

Gunakan skill ini jika user meminta merapikan tampilan terminal, HUD, atau status agar tidak ambigu.

Tujuan:

1. Menghindari istilah yang membingungkan.
2. Menjaga diagnostic internal tetap tersedia.
3. Membuat status mudah dibaca untuk operator dan KTI.

Aturan istilah:

1. Jangan gunakan `override_blocked` sebagai status utama.
2. Gunakan `OVERRIDE_INACTIVE` jika override belum aktif.
3. Gunakan `TAKEOVER_READY` jika sistem siap mengambil alih.
4. Gunakan `TAKEOVER_ACTIVE` jika sistem sedang mengambil alih.
5. Gunakan `MANUAL_AUTHORITY` jika operator memegang kendali.
6. Gunakan `INTERFACE_NOT_READY` jika interface aktuasi belum siap.
7. Gunakan `ACTUATOR_NOT_ENABLED` jika output aktuasi belum diizinkan.
8. Simpan `override_blocked` hanya sebagai diagnostic internal jika masih diperlukan.

Patch tampilan tidak boleh mengubah logic kontrol.

Verifikasi:

1. Compile Python.
2. Cek tidak ada perubahan pada safety logic.
3. Cek status baru tetap informatif.
4. Cek raw diagnostic masih cukup untuk audit.

## 10. Skill 9: Hardware Run Preparation

Gunakan skill ini sebelum user menjalankan pengujian hardware.

Tujuan:

1. Menyiapkan sesi pengujian yang aman.
2. Memastikan logger metrik aktif sesuai kebutuhan.
3. Memastikan snapshot mati jika tidak diminta.
4. Memastikan stop script siap.

Checklist sebelum run:

1. Operator siap.
2. USV diawasi.
3. Area pengujian aman.
4. Obstacle uji aman.
5. Baterai aman.
6. Kamera terpasang.
7. Jetson menyala.
8. CUAV dan RC siap.
9. Manual takeover tersedia.
10. Stop script tersedia.
11. Tidak ada session collision avoidance lain dari repo ini.
12. Tidak ada bridge aktuasi ganda.
13. Logger metrik diarahkan ke folder evidence baru.
14. `save_frames=false` kecuali user meminta snapshot.

Run script yang disarankan jika memang sudah dikonfirmasi user:

```bash
./run_phase7_monitor_no_log.sh
```

Stop script:

```bash
./stop_phase7_safe.sh
```

Jangan menjalankan script ini tanpa izin user.

## 11. Skill 10: Post-Test Evidence Summary

Gunakan skill ini setelah pengujian selesai.

Tujuan:

1. Merangkum data yang berhasil dikumpulkan.
2. Menentukan apakah sesi layak untuk KTI.
3. Menentukan tabel dan grafik yang bisa dibuat.
4. Menemukan kekurangan log untuk sesi berikutnya.

Langkah kerja:

1. Cari folder evidence terbaru.
2. Cek file CSV dan JSON.
3. Cek jumlah baris data.
4. Cek rentang timestamp.
5. Cek distribusi risk class.
6. Cek distribusi command.
7. Cek avoidance cycle.
8. Cek waktu respons.
9. Cek output aktuasi.
10. Cek failsafe dan lost perception.
11. Cek apakah snapshot tidak membebani sesi.

Output yang harus diberikan:

1. Nama folder evidence.
2. File yang tersedia.
3. Durasi data.
4. Jumlah avoidance cycle.
5. Distribusi risk class.
6. Distribusi command.
7. Waktu respons utama.
8. Ringkasan aktuasi.
9. Failsafe/lost perception.
10. Status layak KTI atau belum.
11. Data yang perlu ditambah pada pengujian berikutnya.

## 12. Priority Order

Saat bekerja pada repo ini, gunakan urutan prioritas berikut:

1. Keselamatan hardware.
2. Tidak mengganggu repo dan proses rekan lain.
3. Menjaga manual authority operator.
4. Menjaga STOP dan failsafe tetap konservatif.
5. Menjaga alur collision avoidance tetap stabil.
6. Menjaga logger menghasilkan data KTI.
7. Mengurangi snapshot dan beban runtime.
8. Merapikan tampilan agar tidak ambigu.
9. Melakukan patch kecil jika perlu.
10. Dokumentasi hasil audit.

## 13. Final Instruction

Jika ragu, jangan patch. Lakukan audit, laporkan temuan, dan minta konfirmasi user.

Claude Code harus selalu menganggap sistem ini terhubung dengan hardware nyata dan digunakan bersama sistem rekan lain pada Jetson yang sama. Kesalahan kecil pada repo, proses, atau aktuasi dapat berdampak pada pengujian lapangan.
