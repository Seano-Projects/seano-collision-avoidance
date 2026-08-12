# Kontribusi ke SEANO Collision Avoidance

Kontribusi terhadap pengembangan SEANO Collision Avoidance terbuka melalui issue dan pull request.

Repository ini berkaitan dengan sistem persepsi, pengambilan keputusan, serta integrasi kendali USV. Oleh karena itu, perubahan perlu dilakukan secara terukur dan tetap mempertahankan mekanisme keselamatan yang tersedia.

## Memulai

Fork repository kemudian clone repository hasil fork:

```bash
git clone https://github.com/<username>/seano-collision-avoidance.git
cd seano-collision-avoidance
```

Buat branch baru:

```bash
git checkout -b feat/nama-fitur
```

Contoh penamaan branch:

```text
feat/...
fix/...
docs/...
refactor/...
test/...
```

## Ruang Lingkup Perubahan

Usahakan satu pull request memiliki satu tujuan utama.

Hindari mencampurkan perubahan algoritma, konfigurasi kendaraan, refactor besar, dan dokumentasi apabila perubahan tersebut dapat dipisahkan.

## Verifikasi

Untuk perubahan pada package `seano_vision`:

```bash
cd seano_ca_ws

source /opt/ros/humble/setup.bash

python3 -m compileall -q \
  src/seano_vision/seano_vision

python3 -m pytest \
  src/seano_vision/test -q

./run_ca.sh --dry-check
```

Pastikan seluruh test yang relevan berhasil sebelum membuat pull request.

## Perubahan Safety-Critical

Perubahan pada komponen berikut membutuhkan pemeriksaan tambahan:

```text
auto_takeover_state.py
auto_takeover_manager_node.py
risk_evaluator_node.py
watchdog_failsafe_node.py
guarded_thruster_test_adapter_node.py
thruster_test_safety.py
```

Perubahan tidak boleh:

- menghilangkan prioritas kendali operator;
- melewati safety gate;
- menonaktifkan fail-safe tanpa alasan dan verifikasi;
- membuat publisher RC override yang konflik;
- memasukkan credential MQTT ke repository;
- mengubah sistem eksternal SEANO tanpa kebutuhan yang terdokumentasi.

Perubahan yang memengaruhi aktuasi fisik harus diuji secara bertahap dengan pengawasan operator.

## Commit

Gunakan pesan commit yang singkat dan deskriptif.

Contoh:

```text
feat: improve obstacle tracking
fix: recover AUTO monitoring after operator override
docs: update installation guide
test: add takeover recovery coverage
```

## Pull Request

Deskripsi pull request sebaiknya menjelaskan:

- masalah atau kebutuhan;
- perubahan yang dilakukan;
- komponen yang terdampak;
- cara verifikasi;
- hasil test;
- dampak terhadap safety atau runtime jika ada.

Jangan menyertakan password, token, credential MQTT, runtime log sensitif, atau file konfigurasi privat.
