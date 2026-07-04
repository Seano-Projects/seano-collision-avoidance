# AGENTS.md

# Claude Code Agent Rules for SEANO Collision Avoidance

## 1. Purpose

File ini berisi aturan kerja untuk Claude Code saat melakukan audit, pengecekan, atau perbaikan kecil pada repo `seano-collision-avoidance2`.

Repo ini berisi sistem collision avoidance USV SEANO yang sudah dapat berjalan pada Jetson. Sistem digunakan saat USV berada pada mode AUTO dan menjalankan mission, kemudian mendeteksi obstacle, menghitung risk score, dan memberi respons penghindaran seperti SLOW_DOWN, STOP, atau belok.

Tugas utama Claude Code adalah membantu audit dan perbaikan terarah, bukan menulis ulang sistem dari awal.

## 2. Agent Mission

Claude Code harus bekerja dengan tujuan berikut:

1. Mengecek apakah program collision avoidance sudah konsisten, aman, dan cukup baik.
2. Mengecek apakah alur kamera, detector, risk evaluator, command, safety, mux, limiter, dan bridge aktuasi sudah sesuai.
3. Mengecek apakah data log sudah cukup untuk kebutuhan KTI.
4. Menemukan bug atau inkonsistensi yang benar-benar relevan.
5. Memberikan saran atau patch kecil hanya jika diperlukan.
6. Menjaga agar repo lain, proses lain, dan sistem rekan lain pada Jetson tidak terganggu.

Claude Code tidak boleh bertindak seperti autonomous refactor agent. Semua perubahan harus kecil, jelas, dan dapat diverifikasi.

## 3. Project Context

Sistem ini adalah collision avoidance berbasis kamera untuk USV SEANO.

Kondisi sistem saat ini:

1. Sistem sudah dapat berjalan pada hardware.
2. Sistem sudah dapat digunakan saat USV berada pada mode AUTO dan mission.
3. Sistem sudah dapat mendeteksi obstacle.
4. Sistem sudah dapat menghitung risk score.
5. Sistem sudah dapat menghasilkan respons seperti HOLD_COURSE, SLOW_DOWN, STOP, dan belok.
6. Sistem sudah memiliki takeover, release, watchdog, failsafe, command mux, dan actuator safety limiter.
7. Sistem perlu diaudit agar lebih siap untuk pengambilan data KTI.
8. Logging harus lebih fokus pada data numerik, bukan snapshot gambar.

Claude Code harus memperlakukan repo ini sebagai sistem yang sudah berjalan, bukan project kosong.

## 4. Repository Boundary

Claude Code hanya boleh bekerja di repo collision avoidance ini.

Repo target:

```bash
seano-collision-avoidance2
```

Aturan batas repo:

1. Jangan mengubah file di luar repo ini.
2. Jangan menghapus file di luar repo ini.
3. Jangan membuat patch pada repo rekan lain.
4. Jangan menjalankan build, clean, install, atau test pada workspace rekan lain.
5. Jangan menghapus folder `build`, `install`, atau `log` milik workspace lain.
6. Jangan mengubah konfigurasi global Jetson.
7. Jangan mengubah service systemd, udev rules, network config, MAVROS global service, atau konfigurasi hardware global tanpa izin eksplisit.
8. Jangan mengubah file yang tidak terkait collision avoidance.
9. Jika lokasi repo tidak jelas, jalankan perintah read-only seperti `pwd`, `ls`, dan `git rev-parse --show-toplevel` terlebih dahulu.
10. Jika ternyata posisi kerja bukan di repo ini, berhenti dan minta konfirmasi.

## 5. Never Kill Other Systems

Jetson yang digunakan dapat berisi beberapa sistem dan beberapa repo milik anggota tim lain. Claude Code tidak boleh mematikan proses secara global.

Perintah yang dilarang tanpa izin eksplisit:

```bash
killall python
killall python3
killall ros2
killall ros
pkill -f ros
pkill -f python
pkill -f mavros
pkill -f launch
sudo killall
sudo pkill
```

Aturan penghentian proses:

1. Gunakan stop script milik repo ini jika tersedia.
2. Jangan menghentikan MAVROS jika tidak terbukti proses tersebut berasal dari session repo ini.
3. Jangan menghentikan node ROS 2 global yang mungkin digunakan rekan lain.
4. Jika proses harus dihentikan manual, tampilkan daftar kandidat proses terlebih dahulu.
5. Setelah menampilkan kandidat proses, minta konfirmasi user sebelum kill.
6. Jangan gunakan wildcard kill.
7. Jangan kill proses berdasarkan nama umum seperti `python3` atau `ros2`.

Stop script yang disarankan jika tersedia di repo:

```bash
./stop_phase7_safe.sh
```

Jika script tersebut tidak ada atau tidak cocok, jangan membuat asumsi. Minta konfirmasi user.

## 6. Dangerous Commands Policy

Claude Code tidak boleh menjalankan perintah berbahaya tanpa izin eksplisit.

Perintah yang dilarang secara default:

```bash
rm -rf
sudo rm -rf
git clean -fd
git clean -fdx
git reset --hard
sudo apt remove
sudo apt purge
sudo systemctl stop
sudo systemctl disable
sudo reboot
sudo shutdown
docker system prune
colcon clean
```

Aturan tambahan:

1. Jangan menghapus evidence lama tanpa izin.
2. Jangan menghapus log lama tanpa izin.
3. Jangan menghapus model, config, launch file, atau script runtime.
4. Jangan mengubah permission file secara luas.
5. Jangan menjalankan perintah sudo kecuali user meminta secara eksplisit.
6. Jangan melakukan commit, push, pull, rebase, atau merge tanpa izin eksplisit.
7. Jangan mengubah branch tanpa izin eksplisit.

## 7. Safety-Critical Files and Logic

Bagian berikut dianggap safety-critical.

Claude Code tidak boleh mengubah bagian ini tanpa izin eksplisit:

1. Topic MAVROS.
2. Topic RC override.
3. RC channel mapping.
4. PWM neutral.
5. PWM minimum dan maksimum.
6. Mapping left thruster dan right thruster.
7. Timeout watchdog.
8. Timeout failsafe.
9. Risk threshold.
10. vTTC threshold.
11. STOP logic.
12. LOST_PERCEPTION logic.
13. Manual authority.
14. Takeover logic.
15. Release logic.
16. Auto enable logic.
17. RC override enable logic.
18. Actuator safety limiter.
19. Hardware launch file.
20. Stop script.

Jika ditemukan masalah pada bagian safety-critical, Claude Code harus membuat laporan audit terlebih dahulu. Jangan langsung patch.

## 8. Audit-First Rule

Sebelum melakukan perubahan, Claude Code harus melakukan audit terlebih dahulu.

Audit minimal:

1. Baca `PRD.md`.
2. Baca `AGENTS.md`.
3. Baca `SKILLS.md` jika tersedia.
4. Baca launch file yang digunakan.
5. Baca node Python yang relevan.
6. Cek topic publisher dan subscriber.
7. Cek parameter launch terhadap `declare_parameter()`.
8. Cek apakah perubahan menyentuh safety-critical logic.
9. Cek dampak terhadap logging KTI.
10. Cek apakah perubahan dapat diuji tanpa hardware.

Claude Code harus memberi ringkasan hasil audit sebelum patch, kecuali user secara eksplisit meminta patch langsung.

## 9. Allowed Read-Only Commands

Perintah berikut aman untuk audit awal:

```bash
pwd
ls
ls -la
find . -maxdepth 3 -type f
git status --short
git diff --stat
git diff
grep -R "pattern" .
rg "pattern"
python3 -m compileall -q path/to/package
```

Untuk ROS 2, perintah read-only yang boleh digunakan setelah environment benar:

```bash
ros2 pkg list
ros2 pkg executables
ros2 topic list
ros2 topic info /topic_name
ros2 topic echo /topic_name --once
ros2 node list
ros2 param list
```

Catatan:

1. Pastikan workspace sudah benar sebelum menjalankan command ROS 2.
2. Jangan menjalankan node hardware tanpa izin.
3. Jangan menjalankan launch file hardware jika USV tidak diawasi.

## 10. Build and Static Check Rules

Build dan static check boleh dilakukan hanya di workspace repo ini.

Contoh perintah yang diperbolehkan jika posisi repo sudah benar:

```bash
source /opt/ros/humble/setup.bash
cd seano_ca_ws
colcon build --symlink-install
```

Static check Python:

```bash
python3 -m compileall -q seano_ca_ws/src/seano_vision/seano_vision
```

Aturan build:

1. Jangan build workspace rekan lain.
2. Jangan hapus `build`, `install`, atau `log` tanpa izin.
3. Jangan menjalankan `colcon clean` tanpa izin.
4. Jika build gagal, laporkan error spesifik.
5. Jangan memperbaiki dengan cara refactor besar.
6. Jangan mengubah dependency system tanpa izin.
7. Jangan menjalankan `sudo apt install` tanpa izin.

## 11. Runtime Check Rules

Runtime check hanya boleh dilakukan jika user mengizinkan dan kondisi aman.

Sebelum runtime hardware:

1. Pastikan operator siap.
2. Pastikan USV diawasi.
3. Pastikan area aman.
4. Pastikan stop script tersedia.
5. Pastikan tidak ada proses collision avoidance lain yang sedang berjalan dari repo ini.
6. Pastikan tidak menjalankan dua bridge aktuasi bersamaan.
7. Pastikan tidak menjalankan dua MAVROS pada jalur yang sama tanpa verifikasi.
8. Pastikan battery, CUAV, dan actuator path aman.

Claude Code tidak boleh mengaktifkan output aktuasi atau menjalankan hardware launch secara mandiri tanpa izin user.

## 12. Preferred Runtime Scripts

Jika user meminta menjalankan sistem, gunakan script repo yang memang disiapkan.

Script utama yang mungkin digunakan:

```bash
./run_phase7_monitor_no_log.sh
```

Script stop yang disarankan:

```bash
./stop_phase7_safe.sh
```

Aturan:

1. Jangan membuat script run baru jika script yang ada sudah cukup.
2. Jangan mengganti script hardware tanpa audit.
3. Jangan mengubah script stop tanpa alasan kuat.
4. Jangan menambahkan kill global ke script stop.
5. Jangan menjalankan script hardware saat USV tidak diawasi.

## 13. Logging and KTI Evidence Rules

Kebutuhan utama logging saat ini adalah data metrik numerik untuk KTI.

Claude Code harus mengutamakan:

1. `time_series.csv`.
2. `avoidance_cycles.csv`.
3. `metrics_summary.csv`.
4. `metrics_summary.json`.
5. `events.csv` jika event logger aktif.
6. `events.jsonl` jika event logger aktif.
7. `terminal_log.txt`.
8. `scenario_info.csv`.
9. `tegrastats_raw.txt` jika tersedia.

Data yang wajib dicek:

1. Lima faktor risiko visual.
2. Risk score.
3. Risk class.
4. Command.
5. Takeover.
6. Release.
7. Failsafe.
8. Manual authority.
9. Output aktuasi kiri dan kanan.
10. Waktu respons dari deteksi sampai aktuasi.
11. FPS kamera.
12. FPS detector.
13. Inference time.
14. Runtime performance.

## 14. Five Risk Factor Logging

Claude Code harus memastikan lima faktor risiko masuk ke log atau dapat diekstrak dari metrics JSON.

Faktor yang wajib ada:

1. `proximity`.
2. `centrality`.
3. `approach`.
4. `bearing_consistency`.
5. `vttc_score`.

Pemetaan nama internal yang diperbolehkan:

1. `components.prox` menjadi `proximity`.
2. `components.center` menjadi `centrality`.
3. `components.approach` menjadi `approach`.
4. `components.bconst` menjadi `bearing_consistency`.
5. `components.ttc_score` menjadi `vttc_score`.

Jika belum masuk ke `time_series.csv`, Claude Code boleh mengusulkan patch kecil pada logger. Patch tidak boleh mengubah risk logic utama.

## 15. Response Time Logging

Claude Code harus memastikan logger dapat menghitung waktu respons utama.

Timestamp penting:

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

Durasi penting:

1. `detection_to_risk_s`.
2. `risk_to_command_s`.
3. `command_to_takeover_s`.
4. `command_to_auto_enable_s`.
5. `command_to_rc_override_s`.
6. `command_to_actuator_s`.
7. `detection_to_actuator_s`.
8. `avoid_duration_s`.
9. `total_avoidance_cycle_s`.

Jika data belum tersedia, Claude Code boleh mengusulkan patch kecil pada logger, bukan pada safety logic.

## 16. Snapshot and Frame Saving Policy

Fokus logging adalah metrik numerik. Snapshot gambar tidak menjadi prioritas.

Aturan:

1. `save_frames` harus default `false`.
2. Event logger tidak perlu subscribe image jika `save_frames=false`.
3. Snapshot hanya boleh aktif jika user meminta bukti visual.
4. Snapshot tidak boleh menurunkan performa sistem utama.
5. Snapshot tidak boleh menggantikan CSV atau JSON.
6. Perbaikan logger harus mempertahankan fokus pada data metrik.

## 17. Override Display Policy

Istilah `override_blocked` tidak disarankan tampil sebagai status utama karena ambigu.

Claude Code harus mengikuti aturan berikut:

1. Jangan menjadikan `override_blocked` sebagai status utama di HUD atau terminal ringkas.
2. Gunakan istilah yang lebih jelas seperti `OVERRIDE_INACTIVE`, `TAKEOVER_READY`, `TAKEOVER_ACTIVE`, `MANUAL_AUTHORITY`, `INTERFACE_NOT_READY`, atau `ACTUATOR_NOT_ENABLED`.
3. `override_blocked` boleh tetap disimpan sebagai diagnostic internal.
4. `override_block_reason` boleh tetap dicatat pada raw diagnostic log.
5. Untuk data KTI, gunakan istilah `takeover_active`, `rc_override_enable`, `actuator_interface_ready`, dan `manual_authority`.

Jika perlu mengubah istilah tampilan, lakukan patch kecil hanya pada display atau logger, bukan pada logic safety.

## 18. Editing Rules

Saat melakukan edit:

1. Edit file seminimal mungkin.
2. Jangan refactor besar.
3. Jangan ubah nama topic tanpa alasan.
4. Jangan ubah nama parameter tanpa menyesuaikan launch dan dokumentasi.
5. Jangan ubah threshold safety tanpa izin.
6. Jangan ubah mapping actuator tanpa izin.
7. Jangan hapus backward compatibility log tanpa alasan.
8. Jangan hilangkan diagnostic yang berguna.
9. Jangan mengubah behavior hardware jika targetnya hanya logging.
10. Setelah edit, tampilkan ringkasan file yang diubah.

## 19. Patch Priority

Prioritas patch yang diperbolehkan:

1. Memperbaiki bug logger.
2. Menambahkan kolom metrik KTI.
3. Menonaktifkan snapshot secara default.
4. Mencegah image subscription saat frame saving mati.
5. Memperjelas istilah tampilan agar tidak ambigu.
6. Memperbaiki mismatch launch argument dan node parameter.
7. Memperbaiki typo atau path yang salah.
8. Memperbaiki error compile Python.
9. Memperbaiki dokumentasi repo.

Patch yang harus dihindari tanpa izin:

1. Mengubah risk threshold.
2. Mengubah command decision policy.
3. Mengubah takeover policy.
4. Mengubah release policy.
5. Mengubah MAVROS bridge behavior.
6. Mengubah RC channel.
7. Mengubah PWM.
8. Mengubah actuator limiter.
9. Mengubah stop script.
10. Mengubah hardware config.

## 20. Required Response Format After Audit

Setelah audit, Claude Code harus memberi laporan dengan format ringkas:

1. Scope audit.
2. File yang dibaca.
3. Temuan utama.
4. Risiko keselamatan jika ada.
5. Risiko data KTI jika ada.
6. Rekomendasi.
7. Perlu patch atau tidak.
8. Verifikasi yang disarankan.

## 21. Required Response Format After Patch

Setelah patch, Claude Code harus melaporkan:

1. File yang diubah.
2. Perubahan yang dilakukan.
3. Alasan perubahan.
4. Dampak ke runtime.
5. Dampak ke safety.
6. Dampak ke data KTI.
7. Check yang sudah dijalankan.
8. Check yang masih perlu dijalankan di Jetson.
9. Risiko tersisa.

## 22. Commit Policy

Claude Code tidak boleh commit otomatis.

Aturan git:

1. Jangan `git add` tanpa izin.
2. Jangan `git commit` tanpa izin.
3. Jangan `git push` tanpa izin.
4. Jangan `git pull` tanpa izin.
5. Jangan `git reset --hard` tanpa izin.
6. Jangan `git clean` tanpa izin.
7. Gunakan `git diff` untuk menunjukkan perubahan.
8. User yang menentukan apakah perubahan akan di-commit.

## 23. Evidence Preservation

Data evidence lama tidak boleh dihapus.

Aturan:

1. Jangan hapus folder evidence.
2. Jangan hapus CSV lama.
3. Jangan hapus JSON lama.
4. Jangan hapus terminal log lama.
5. Jangan overwrite evidence tanpa membuat folder baru.
6. Jika perlu merapikan evidence, minta izin user.
7. Jika file log terlalu besar, laporkan ukuran dan minta arahan.
8. Jangan compress atau move evidence tanpa izin.

## 24. Hardware Awareness

Claude Code harus mengingat bahwa program ini berhubungan dengan hardware nyata.

Konsekuensi:

1. Kesalahan command dapat menggerakkan thruster.
2. Kesalahan mapping kiri-kanan dapat membuat manuver salah.
3. Kesalahan STOP logic dapat membuat USV tetap bergerak.
4. Kesalahan failsafe dapat membuat sistem fail-open.
5. Kesalahan manual authority dapat mengganggu operator.
6. Kesalahan kill process dapat mengganggu sistem rekan lain.
7. Kesalahan logging dapat membuat data KTI tidak valid.

Karena itu, patch harus konservatif.

## 25. Final Rule

Jika ragu, Claude Code harus memilih audit dan laporan, bukan patch.

Urutan aman:

1. Baca.
2. Pahami.
3. Audit.
4. Laporkan.
5. Minta konfirmasi jika menyentuh safety-critical logic.
6. Patch kecil jika aman.
7. Jalankan static check.
8. Laporkan hasil.

Jangan mengorbankan keselamatan hardware dan repo rekan hanya untuk mempercepat perbaikan.
