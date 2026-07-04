# SEANO Collision Avoidance System
## Product Requirements Document for Claude Code Audit and KTI Metrics Logging

## 1. Purpose

Dokumen ini menjelaskan kebutuhan utama sistem, batasan kerja, target audit, dan kebutuhan data metrik untuk repo collision avoidance pada USV SEANO.

Sistem pada repo ini sudah berada pada tahap implementasi berjalan. Sistem sudah dapat dijalankan pada Jetson, digunakan saat USV berada pada mode AUTO dan sedang menjalankan mission, mendeteksi obstacle melalui kamera, menghitung tingkat risiko, lalu memberi respons penghindaran seperti melambat, berhenti, atau berbelok.

Tujuan dokumen ini bukan untuk membuat ulang sistem dari awal. Tujuan utama dokumen ini adalah memberi arahan yang jelas kepada Claude Code agar dapat mengecek kualitas program, menemukan potensi masalah, memperbaiki bagian yang memang perlu diperbaiki, dan memastikan data log yang dihasilkan cukup kuat untuk pengolahan KTI.

## 2. Current System Status

Status sistem saat ini adalah sebagai berikut.

1. Sistem collision avoidance sudah dapat berjalan pada USV SEANO.
2. Sistem dapat digunakan saat USV berada pada mode AUTO dan menjalankan mission.
3. Kamera USB digunakan sebagai sensor visual utama untuk melihat area depan wahana.
4. Detector node sudah dapat menghasilkan data deteksi obstacle.
5. Risk evaluator sudah dapat mengubah hasil deteksi menjadi risk score.
6. Sistem sudah memiliki command penghindaran seperti HOLD_COURSE, SLOW_DOWN, TURN_RIGHT_SLOW, TURN_LEFT_SLOW, TURN_RIGHT, TURN_LEFT, dan STOP.
7. Sistem sudah dapat memberikan respons penghindaran ketika obstacle dinilai berbahaya.
8. Respons penghindaran yang sudah berjalan mencakup pelambatan, penghentian, dan manuver belok.
9. Sistem sudah memiliki mekanisme safety seperti watchdog, failsafe, command mux, takeover, release, dan actuator safety limiter.
10. Logging sudah tersedia, tetapi perlu diarahkan agar lebih fokus pada data metrik numerik untuk KTI, bukan snapshot gambar.

## 3. System Scope

Ruang lingkup repo ini hanya untuk sistem collision avoidance berbasis kamera pada USV SEANO.

Bagian yang termasuk dalam ruang lingkup:

1. Akuisisi citra kamera.
2. Deteksi obstacle.
3. Evaluasi risiko visual.
4. Pengambilan keputusan command collision avoidance.
5. Watchdog dan failsafe.
6. Takeover dan release.
7. Command mux.
8. Actuator safety limiter.
9. Bridge menuju aktuasi melalui jalur yang sudah tersedia.
10. Logging data pengujian.
11. Penyediaan data metrik untuk KTI.

Bagian yang tidak termasuk dalam ruang lingkup:

1. Membuat firmware ArduPilot baru.
2. Membuat autopilot penuh.
3. Membuat global path planning.
4. Membuat sistem full COLREGs compliance.
5. Mengubah sistem milik rekan lain pada Jetson.
6. Mengubah konfigurasi utama CUAV, MAVROS, RC channel, atau PWM tanpa izin eksplisit.
7. Menghapus data, proses, folder, workspace, atau repo lain di Jetson.

## 4. Runtime Flow

Alur utama sistem yang harus dipertahankan adalah:

1. Kamera USB mengambil citra area depan USV.
2. camera node memublikasikan citra ke topic ROS 2.
3. detector node memproses citra dan menghasilkan obstacle detection.
4. risk evaluator node menghitung risk score, risk class, target utama, dan command awal.
5. watchdog dan failsafe memeriksa validitas data, keterlambatan data, dan kondisi tidak aman.
6. mode manager mengelola kondisi MISSION, AVOID, REJOIN, atau FAILSAFE.
7. command mux memilih command yang valid dan aman.
8. actuator safety limiter membatasi keluaran aktuasi agar tetap aman.
9. bridge aktuasi meneruskan output ke jalur kendali yang tersedia.
10. CUAV, ArduPilot, dan differential thruster menjalankan respons fisik wahana.

Claude Code harus menjaga alur ini. Perubahan besar pada alur runtime hanya boleh dilakukan jika diminta secara eksplisit.

## 5. Main Product Goals

Sistem harus memenuhi tujuan berikut.

1. Menjalankan collision avoidance saat USV berada pada mode AUTO dan mission.
2. Mendeteksi obstacle pada bidang pandang kamera.
3. Mengubah hasil deteksi menjadi risk score yang dapat dijelaskan.
4. Menghasilkan command penghindaran sesuai tingkat risiko.
5. Melakukan takeover ketika obstacle dinilai berbahaya.
6. Melakukan release ketika kondisi kembali aman.
7. Menjaga otoritas manual operator.
8. Memberikan respons aman saat data kamera, deteksi, atau command tidak valid.
9. Mencatat data metrik yang cukup untuk analisis KTI.
10. Tidak mengganggu repo, proses, atau sistem milik rekan lain pada Jetson yang sama.

## 6. Non-Goals

Sistem ini tidak boleh diklaim sebagai:

1. Sistem keselamatan maritim final.
2. Sistem collision avoidance tersertifikasi.
3. Sistem autopilot penuh.
4. Sistem full COLREGs.
5. Sistem global path planner.
6. Sistem pengukuran jarak absolut obstacle dalam meter.
7. Sistem yang dapat melihat obstacle di luar bidang pandang kamera.
8. Sistem yang dapat bekerja aman tanpa operator.
9. Sistem yang bebas risiko pada semua kondisi perairan, pencahayaan, cuaca, dan gelombang.

## 7. Claude Code Audit Goals

Claude Code digunakan untuk mengecek apakah program sudah baik, aman, konsisten, dan cukup lengkap untuk kebutuhan KTI.

Audit harus mencakup:

1. Konsistensi launch file dengan parameter pada node.
2. Konsistensi publisher dan subscriber ROS 2.
3. Konsistensi alur kamera, detector, risk evaluator, command, safety, mux, limiter, dan bridge aktuasi.
4. Konsistensi risk score terhadap command yang dihasilkan.
5. Konsistensi takeover dan release.
6. Konsistensi failsafe saat data visual tidak valid atau terlambat.
7. Konsistensi manual authority operator.
8. Konsistensi output aktuasi kiri dan kanan terhadap command.
9. Kelengkapan data log untuk KTI.
10. Potensi beban runtime berlebih dari debug image, snapshot, atau logging yang tidak perlu.
11. Potensi istilah ambigu pada terminal, HUD, atau log.
12. Potensi bug yang dapat membuat data KTI tidak lengkap.

Claude Code tidak boleh melakukan rewrite besar. Perubahan harus kecil, jelas, dapat diuji, dan tidak boleh mengubah bagian safety-critical tanpa izin eksplisit.

## 8. Required KTI Metrics

Logging harus diarahkan untuk menghasilkan data yang kuat untuk Bab IV KTI. Fokus utama adalah data numerik yang dapat diolah menjadi tabel, grafik, dan pembahasan.

### 8.1 Five Risk Factor Metrics

Lima faktor utama penilaian risiko visual wajib dicatat.

1. proximity.
2. centrality.
3. approach.
4. bearing_consistency.
5. vttc_score.

Jika nama internal program menggunakan nama berbeda, pemetaan yang disarankan adalah:

1. components.prox menjadi proximity.
2. components.center menjadi centrality.
3. components.approach menjadi approach.
4. components.bconst menjadi bearing_consistency.
5. components.ttc_score menjadi vttc_score.

Data pendukung yang juga perlu dicatat:

1. risk_score.
2. risk_class.
3. confidence.
4. area_ratio.
5. bottom_y_ratio.
6. x_ratio.
7. bearing_deg.
8. bearing_rate_dps.
9. dlog_area_dt.
10. vttc_s.
11. dominant_factor.
12. reason_codes.

### 8.2 Detection and Perception Metrics

Data persepsi yang perlu dicatat:

1. timestamp.
2. camera_fps.
3. image_publish_fps.
4. detector_fps.
5. inference_ms.
6. detector_process_ms.
7. image_age_s.
8. detection_age_s.
9. num_detections.
10. selected_target_id.
11. selected_target_class.
12. selected_target_confidence.
13. selected_target_bbox_x.
14. selected_target_bbox_y.
15. selected_target_bbox_w.
16. selected_target_bbox_h.
17. selected_target_area_ratio.
18. selected_target_bottom_y_ratio.
19. selected_target_bearing_deg.
20. local_perception_state.
21. lost_perception_status.
22. freeze_status.

### 8.3 Risk and Command Metrics

Data risk dan command yang perlu dicatat:

1. risk_score.
2. risk_raw jika tersedia.
3. risk_class.
4. raw_command.
5. safe_command.
6. selected_command.
7. command_source.
8. command_reason.
9. command_switch_count.
10. avoid_active.
11. takeover_active.
12. release_status.
13. mode_state.
14. failsafe_active.
15. failsafe_reason.
16. manual_authority.

Data ini harus dapat digunakan untuk membuat distribusi risk class dan distribusi command, misalnya persentase HOLD_COURSE, SLOW_DOWN, TURN_RIGHT_SLOW, TURN_LEFT_SLOW, TURN_RIGHT, TURN_LEFT, dan STOP.

### 8.4 Response Time Metrics

Waktu respons adalah data penting untuk KTI. Logger harus mendukung perhitungan waktu dari awal obstacle terdeteksi sampai sistem memberi respons.

Timestamp yang perlu dicatat:

1. first_detection_time_sec.
2. first_risk_time_sec.
3. first_hazard_command_time_sec.
4. takeover_start_time_sec.
5. auto_enable_time_sec.
6. rc_override_enable_time_sec.
7. first_actuator_output_time_sec.
8. avoid_start_time_sec.
9. rejoin_start_time_sec.
10. mission_return_time_sec.
11. cycle_end_time_sec.

Durasi yang perlu dihitung:

1. detection_to_risk_s.
2. risk_to_command_s.
3. command_to_takeover_s.
4. command_to_auto_enable_s.
5. command_to_rc_override_s.
6. command_to_actuator_s.
7. detection_to_actuator_s.
8. risk_to_avoid_s.
9. avoid_duration_s.
10. avoid_to_rejoin_s.
11. rejoin_to_mission_s.
12. total_avoidance_cycle_s.
13. time_in_high_risk_s.
14. time_in_failsafe_s.

Jika sebagian timestamp belum tersedia pada program saat ini, Claude Code boleh mengusulkan penambahan kecil pada logger. Penambahan harus dilakukan tanpa mengubah logika keselamatan utama.

### 8.5 Actuator Metrics

Data aktuasi yang perlu dicatat:

1. auto_left_cmd.
2. auto_right_cmd.
3. selected_left_cmd.
4. selected_right_cmd.
5. final_left_cmd.
6. final_right_cmd.
7. manual_left_cmd.
8. manual_right_cmd.
9. max_abs_left_cmd.
10. max_abs_right_cmd.
11. max_abs_diff_cmd.
12. actuator_limiter_active.
13. actuator_limiter_reason.
14. actuator_interface_ready.
15. rc_override_enable.
16. takeover_active.

Data ini harus dapat digunakan untuk membuktikan bahwa command collision avoidance benar-benar diterjemahkan menjadi output kiri dan kanan pada differential thruster.

### 8.6 Runtime Performance Metrics

Data performa runtime yang perlu dicatat:

1. camera_fps.
2. detector_fps.
3. inference_ms.
4. risk_evaluator_process_ms.
5. command_process_ms jika tersedia.
6. logger_process_ms jika tersedia.
7. CPU usage jika tersedia.
8. GPU usage jika tersedia.
9. RAM usage jika tersedia.
10. temperature jika tersedia.
11. stale_count.
12. lost_perception_count.
13. failsafe_count.
14. node_restart_count jika tersedia.

## 9. Logging Policy

Fokus logging untuk tahap ini adalah data numerik, bukan snapshot gambar.

Kebijakan logging:

1. Output utama harus berupa CSV dan JSON.
2. time_series.csv harus menjadi data utama untuk grafik dan analisis waktu.
3. avoidance_cycles.csv harus memuat ringkasan setiap episode penghindaran.
4. metrics_summary.csv atau metrics_summary.json harus memuat ringkasan statistik pengujian.
5. events.csv atau events.jsonl boleh digunakan untuk mencatat event penting.
6. Snapshot gambar tidak menjadi prioritas.
7. save_frames harus false secara default.
8. Logger tidak boleh subscribe image jika save_frames=false.
9. HUD atau terminal monitor boleh digunakan untuk pengawasan, tetapi bukan bukti utama KTI.
10. Data metrik harus cukup untuk diolah ulang setelah pengujian selesai.

Output yang disarankan pada satu sesi pengujian:

1. scenario_info.csv.
2. terminal_log.txt.
3. time_series.csv.
4. avoidance_cycles.csv.
5. metrics_summary.csv.
6. metrics_summary.json.
7. events.csv jika event logger aktif.
8. events.jsonl jika event logger aktif.
9. tegrastats_raw.txt jika tersedia.

## 10. Snapshot Policy

Snapshot gambar tidak digunakan sebagai fokus utama pengambilan data.

Aturan snapshot:

1. save_frames harus default false.
2. Snapshot hanya boleh diaktifkan jika user secara eksplisit meminta bukti visual.
3. Snapshot tidak boleh membuat performa sistem turun signifikan.
4. Snapshot tidak boleh menggantikan data CSV atau JSON.
5. Jika snapshot dinonaktifkan, program tidak perlu subscribe image hanya untuk logger.
6. Untuk KTI, data numerik lebih diutamakan daripada gambar snapshot.

## 11. Override Status Display Policy

Istilah override_blocked tidak disarankan tampil sebagai status utama karena dapat menimbulkan ambiguitas.

Alasan:

1. Istilah override_blocked dapat terbaca seperti kegagalan sistem.
2. Padahal kondisi tersebut bisa berarti override belum aktif, takeover belum diperlukan, interface aktuator belum dikonfirmasi, atau sistem sedang menjaga output agar tidak diteruskan.
3. Untuk pembahasan KTI, istilah ini dapat membuat interpretasi menjadi tidak jelas.

Kebijakan:

1. Jangan tampilkan override_blocked sebagai status utama di HUD atau terminal ringkas.
2. Gunakan istilah yang lebih operasional.
3. Istilah yang disarankan: OVERRIDE_INACTIVE, TAKEOVER_READY, TAKEOVER_ACTIVE, MANUAL_AUTHORITY, INTERFACE_NOT_READY, atau ACTUATOR_NOT_ENABLED.
4. override_blocked boleh tetap disimpan sebagai diagnostic internal.
5. override_block_reason boleh tetap dicatat pada raw diagnostic log.
6. Untuk KTI, gunakan istilah takeover_active, rc_override_enable, actuator_interface_ready, dan manual_authority.

## 12. Safety Requirements

Bagian keselamatan dianggap safety-critical. Claude Code tidak boleh mengubah bagian ini tanpa izin eksplisit dari user.

Bagian safety-critical:

1. MAVROS topic.
2. RC override topic.
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
16. Actuator safety limiter.
17. Stop script.
18. Auto enable logic.
19. RC override enable logic.

Jika Claude Code menemukan masalah pada bagian safety-critical, Claude Code harus membuat laporan audit terlebih dahulu. Jangan langsung patch bagian tersebut.

## 13. Repository Boundary Requirements

Jetson digunakan oleh beberapa sistem dan beberapa repo. Claude Code hanya boleh bekerja pada repo collision avoidance ini.

Aturan batas repo:

1. Hanya bekerja di repo seano-collision-avoidance2.
2. Jangan mengubah repo lain.
3. Jangan menghapus file atau folder di luar repo ini.
4. Jangan menjalankan rm -rf di luar repo ini.
5. Jangan menjalankan git clean tanpa izin eksplisit.
6. Jangan menghapus build, install, atau log milik workspace lain.
7. Jangan kill proses global seperti killall python, killall ros2, pkill -f ros, atau perintah serupa.
8. Jangan menghentikan MAVROS atau service lain yang mungkin dipakai sistem rekan.
9. Jika perlu menghentikan program, gunakan stop script milik repo ini.
10. Jika proses yang harus dihentikan tidak jelas asalnya, tampilkan kandidat proses dan minta konfirmasi user.

## 14. Runtime Safety Rules

Saat melakukan pengecekan runtime pada Jetson:

1. Pastikan posisi kerja berada di repo yang benar.
2. Pastikan workspace yang digunakan adalah workspace collision avoidance.
3. Jangan menjalankan launch hardware jika operator belum siap.
4. Jangan mengaktifkan output aktuasi jika USV tidak diawasi.
5. Jangan menjalankan test yang dapat menggerakkan thruster tanpa izin.
6. Jangan menjalankan dua bridge aktuasi secara bersamaan.
7. Jangan menjalankan dua MAVROS pada jalur yang sama tanpa verifikasi.
8. Jangan mengubah mode flight controller tanpa instruksi user.
9. Jangan mengubah parameter hardware saat sistem sedang berjalan.
10. Jangan menguji actuator output jika area pengujian tidak aman.

## 15. Acceptance Criteria for Valid KTI Data

Satu sesi pengujian dianggap layak untuk data KTI apabila memenuhi syarat berikut:

1. Kamera aktif selama pengujian.
2. Detector berjalan.
3. Risk score tercatat.
4. Lima faktor risiko tercatat atau dapat diekstrak.
5. Command tercatat.
6. Takeover atau avoid state tercatat.
7. Output aktuasi kiri dan kanan tercatat.
8. Waktu respons dapat dihitung.
9. Failsafe tercatat jika terjadi.
10. Manual authority tercatat jika operator mengambil alih.
11. Data tersedia dalam CSV atau JSON.
12. Tidak bergantung pada snapshot gambar sebagai bukti utama.
13. Tidak ada repo lain yang terganggu selama pengujian.
14. Tidak terjadi tabrakan pada skenario yang diklaim berhasil.

## 16. Expected KTI Tables and Graphs

Log harus mendukung pembuatan tabel dan grafik berikut:

1. Tabel konfigurasi pengujian.
2. Tabel performa kamera dan detector.
3. Tabel hasil deteksi obstacle.
4. Tabel lima faktor risiko visual.
5. Tabel distribusi risk class.
6. Tabel distribusi command.
7. Tabel waktu respons.
8. Tabel output aktuasi kiri dan kanan.
9. Tabel failsafe dan lost perception.
10. Tabel pemenuhan kebutuhan sistem.
11. Grafik risk score terhadap waktu.
12. Grafik lima faktor risiko terhadap waktu.
13. Grafik command terhadap waktu.
14. Grafik left_cmd dan right_cmd terhadap waktu.
15. Grafik waktu respons per avoidance cycle.
16. Grafik inference time atau FPS.
17. Grafik resource Jetson jika data tersedia.

## 17. Definition of Successful Avoidance Cycle

Satu avoidance cycle dianggap berhasil apabila:

1. Obstacle terdeteksi.
2. Risk score naik melewati threshold yang sesuai.
3. Sistem menghasilkan command penghindaran.
4. Takeover atau avoid state aktif.
5. Output aktuasi berubah sesuai command.
6. USV tidak menabrak obstacle.
7. Setelah risiko turun, sistem melakukan release, REJOIN, atau kembali ke MISSION.
8. Timestamp utama tercatat.
9. Tidak ada failsafe yang tidak dapat dijelaskan.
10. Operator tetap memiliki jalur manual recovery.

## 18. Definition of Invalid Evidence

Sesi pengujian dianggap tidak layak sebagai evidence utama apabila:

1. Kamera tidak aktif.
2. Detector tidak berjalan.
3. Risk score tidak tercatat.
4. Lima faktor risiko tidak tersedia.
5. Command tidak tercatat.
6. Output aktuasi tidak tercatat.
7. Waktu respons tidak dapat dihitung.
8. Logger tidak berjalan atau file log kosong.
9. Sistem masuk failsafe tetapi alasan tidak tercatat.
10. Ada intervensi manual tetapi tidak tercatat.
11. Terjadi tabrakan pada skenario yang diklaim berhasil.
12. Data hanya berupa snapshot tanpa CSV atau JSON.
13. Pengujian mengganggu repo atau proses milik rekan lain.

## 19. Recommended Priority Improvements

Prioritas perbaikan yang disarankan:

1. Audit event logger agar fokus pada data metrik.
2. Pastikan save_frames default false.
3. Pastikan logger tidak subscribe image saat save_frames=false.
4. Pastikan lima faktor risiko masuk ke time_series.csv.
5. Pastikan first_detection_time_sec tersedia.
6. Pastikan first_hazard_command_time_sec tersedia.
7. Pastikan first_actuator_output_time_sec tersedia.
8. Pastikan detection_to_actuator_s dapat dihitung.
9. Pastikan avoidance_cycles.csv memuat durasi penghindaran.
10. Pastikan metrics_summary memuat distribusi risk class dan command.
11. Sembunyikan override_blocked dari tampilan utama.
12. Simpan detail override hanya sebagai diagnostic internal jika masih diperlukan.

## 20. Change Control

Setiap perubahan program harus mengikuti aturan berikut:

1. Jelaskan masalah yang ditemukan.
2. Jelaskan file yang diperiksa.
3. Jelaskan file yang diubah.
4. Jelaskan alasan teknis perubahan.
5. Jelaskan dampak terhadap keselamatan.
6. Jelaskan cara verifikasi.
7. Jalankan static check jika memungkinkan.
8. Jangan refactor besar tanpa kebutuhan.
9. Jangan mengubah safety threshold tanpa izin.
10. Jangan mengubah MAVROS, RC channel, PWM, atau mapping aktuator tanpa izin.
11. Jangan commit otomatis.
12. Jangan menghapus evidence lama tanpa izin.
13. Jangan menyentuh repo lain.

## 21. Final Expectation

Hasil akhir yang diharapkan dari repo ini adalah sistem collision avoidance yang:

1. Berjalan pada USV SEANO.
2. Dapat mendeteksi obstacle di depan wahana.
3. Dapat menghitung risk score secara terukur.
4. Dapat menjelaskan risk score melalui lima faktor risiko visual.
5. Dapat menghasilkan command penghindaran yang sesuai.
6. Dapat melakukan takeover dan release secara aman.
7. Dapat menjaga otoritas manual operator.
8. Dapat mencatat data metrik lengkap untuk KTI.
9. Dapat diaudit oleh Claude Code tanpa merusak alur sistem.
10. Tidak mengganggu repo, proses, atau sistem rekan lain pada Jetson.
