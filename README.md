# seano-collision-avoidance

Sistem collision avoidance berbasis vision (kamera) untuk USV (Unmanned Surface Vehicle) SEANO, dipakai untuk uji lapangan di danau. Mendeteksi objek di sekitar kapal lewat YOLOv8, mengevaluasi tingkat risiko, dan mengirim perintah penghindaran/override ke flight controller lewat MAVROS.

Platform: Jetson Orin | ROS2 Humble | YOLOv8 | ArduRover/ArduPilot (MAVLink/MAVROS)

## Dokumentasi

Proyek ini sudah punya dokumentasi yang cukup lengkap di beberapa file terpisah:

| File | Isi |
|---|---|
| `PRD.md` | Tujuan proyek, target use case, dan requirement sistem. |
| `AGENTS.md` | Panduan kerja untuk AI coding assistant di repo ini — repo ini diperlakukan sebagai kode safety-critical untuk USV yang beroperasi di air terbuka, jadi perubahan harus konservatif dan mudah diverifikasi. |
| `SKILLS.md` | Skill/kemampuan khusus yang relevan untuk pengembangan di repo ini. |
| `seano_ca_ws/README.md` | Analisis teknis mendalam: arsitektur pipeline, penjelasan tiap node, alur deteksi-ke-penghindaran, logika mode switching, dan catatan masalah yang ditemukan selama pengembangan. |
| `docs/` | Catatan teknis tambahan (contoh: `PHASE7_ACTUATOR_INTERFACE_NOTES.md`, audit gate severity command). |

## Struktur Folder

```
seano_ca_ws/src/seano_vision/  -> package ROS2 utama (deteksi, evaluasi risiko, kontrol)
seano_ca_ws/                   -> workspace ROS2 (colcon)
docs/                          -> catatan teknis tambahan
```

## Catatan

Tidak ada koneksi MQTT atau kredensial eksternal di sistem ini — komunikasi terjadi lokal antara kamera, ROS2/YOLOv8, dan MAVROS/flight controller di perangkat yang sama.

Untuk cara menjalankan, kalibrasi, dan detail evidence pengujian Phase 7, lihat `seano_ca_ws/README.md` dan `docs/`.
