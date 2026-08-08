# SEANO Collision Avoidance ROS 2 Workspace

Workspace ROS 2 Humble untuk sistem collision avoidance USV SEANO.

## Runtime Utama KTI

Runtime utama yang digunakan pada implementasi dan pengujian adalah:

    ./run_pool_auto_takeover_test.sh

Alur utama sistem:

    AUTO / FOLLOWING ROUTE
            |
            v
    Obstacle dan risiko terdeteksi
            |
            v
    AUTO -> MANUAL takeover
            |
            v
    Collision avoidance aktif
            |
            v
    HOLD / SLOW / TURN / STOP
            |
            v
    Kondisi kembali aman
            |
            v
    Release collision avoidance
            |
            v
    MANUAL -> AUTO
            |
            v
    Kembali mengikuti jalur misi

Runtime ini menggunakan MAVROS eksternal dan jalur `/usv/thruster` yang telah tersedia pada sistem SEANO.

Konfigurasi utama:

    use_mavros=false
    use_rc_override_bridge=false
    use_mode_manager=false
    sole mode owner=auto_takeover_manager_node

HUD:

    /ca/auto_takeover/debug_image

Web video:

    http://<JETSON_IP>:8080

## Pemeriksaan Sebelum Run

Dry check:

    ./run_pool_auto_takeover_test.sh --dry-check

Dry check tidak menjalankan node ROS, tidak membuka koneksi MQTT, dan tidak melakukan perubahan mode maupun arm/disarm FCU.

## Terminal Setup

    cd ~/resource_git/seano-collision-avoidance2/seano_ca_ws
    source /opt/ros/humble/setup.bash
    source install/setup.bash
    export ROS_DOMAIN_ID=0

## TensorRT Model

Model operasional:

    src/seano_vision/models/yolov8n.engine

Konfigurasi:

    precision: FP16
    input size: 416 x 416
    batch size: 1

File TensorRT `.engine` dibuat pada NVIDIA Jetson dan tidak disimpan di Git.

## Supporting Runners

Runner berikut tetap dipertahankan sebagai baseline dan diagnostic tool:

- `run_pool_existing_control_path.sh`
  Safe preview tanpa hardware output.

- `run_pool_thruster_hardware_test.sh`
  Guarded MANUAL-mode thruster diagnostic.

- `run_pool_auto_takeover_test.sh`
  Runtime utama KTI untuk AUTO takeover, collision avoidance, release, dan AUTO restoration.

## Build dan Test

    source /opt/ros/humble/setup.bash

    colcon build --symlink-install

    python3 -m compileall -q src/seano_vision/seano_vision

    bash -n run_pool_existing_control_path.sh
    bash -n run_pool_thruster_hardware_test.sh
    bash -n run_pool_auto_takeover_test.sh

    python3 -m pytest src/seano_vision/test -q

Baseline test terakhir:

    299 passed

## Safety Rules

- Jalankan hanya satu collision-avoidance profile pada satu waktu.
- Runtime utama KTI adalah `run_pool_auto_takeover_test.sh`.
- Jangan menjalankan MAVROS kedua dari workspace ini.
- Jangan membuat publisher RC override kedua.
- Gunakan `/usv/thruster` sebagai jalur RC override yang telah tersedia.
- Jangan mengubah atau menghentikan startup service eksternal SEANO.
- Simpan credential MQTT di luar repository.
- Operator harus tetap memiliki akses kendali manual dan emergency stop.
- Hentikan runtime menggunakan `Ctrl+C` pada terminal yang menjalankannya.
