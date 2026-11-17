# ESP32 ile Raspberry Pi Haberleşmesi: V1 Eğim Alarmı

ESP32, MPU-6050 sensörünü I²C ile okuyup ölçümleri UART üzerinden Raspberry Pi 4'e gönderir; seçilen ekleme V1 Eğim Alarmı, Pi'de eğim açısını hesaplar ve eşik aşılınca ESP32'deki LED'i yakar.

Ayşe Berra Özdamar, 2430131009. İleri Gömülü Sistemler, Dr. Murat Sürücü.

> Yönerge ESP32-S3-DevKitC-1 için yazılmıştır. Bu projede ESP32 DEVKIT V1 kullanılır, bu nedenle derleme hedefi ve I²C pinleri farklıdır. DEVKIT V1 kullanımı Lab 1 ve Lab 3 raporlarında Dr. Murat Sürücü tarafından onaylanmıştır.

## Malzeme

| Malzeme | Adet |
| --- | --- |
| ESP32 DEVKIT V1 ve USB veri kablosu | 1 |
| Raspberry Pi 4, güç kaynağı (5,1 V / 3 A), microSD | 1 |
| MPU-6050 modülü (GY-521) | 1 |
| LED ve 330 Ω direnç | 1 |
| Dişi-dişi ve erkek-dişi atlama kabloları | ~10 |

## Bağlantı tablosu

| ESP32 pini | Bağlandığı yer | Not |
| --- | --- | --- |
| GPIO17 (TX2) | Pi pin 10 (GPIO15 RXD) | çapraz |
| GPIO18 | Pi pin 8 (GPIO14 TXD) | çapraz |
| GND | Pi pin 6 (GND) | ortak toprak zorunlu |
| 3V3 | MPU-6050 VCC | 3,3 V |
| GND | MPU-6050 GND | |
| GPIO21 | MPU-6050 SDA | I²C |
| GPIO22 | MPU-6050 SCL | I²C |
| GPIO4 | 330 Ω → LED → GND | komutla sürülür |

Kartlar ayrı USB kablolarından beslenir. 3V3 ve 5V hatları kartlar arasında birleştirilmez; Pi'nin 5V pinleri (2 ve 4) hiçbir sinyal hattına bağlanmaz.

## ESP32 derleme ve yükleme

Şablon ESP32-S3 için yazılmıştır; DEVKIT V1 için `esp32/main/main.c` içinde `PIN_SDA` 21, `PIN_SCL` 22 yapılmıştır. Başka kod değişikliği yoktur.

ESP-IDF ortamı açık bir terminalde çalıştırın. Port adı bilgisayara göre değişir; macOS'ta `ls /dev/cu.*` ile bulunur.

```bash
cd esp32
idf.py set-target esp32
idf.py build
idf.py -p /dev/cu.usbserial-0001 flash monitor
```

Monitörde `MPU-6050 bulundu` mesajı görünmelidir. `Sensör yok: sentetik veri gönderilecek` yazıyorsa kablolamayı kontrol edin. Çıkmak için `Ctrl+]` tuşlarına basın.

## Raspberry Pi kurulum ve çalıştırma

Seri portu bir kez açın: `sudo raspi-config` içinde Interface Options > Serial Port yolunu izleyin; login shell over serial = **No**, serial port hardware = **Yes**. Sonra Pi'yi yeniden başlatın.

```bash
ls -l /dev/serial0
groups
```

`groups` çıktısında `dialout` görünmelidir. Görünmüyorsa `sudo usermod -aG dialout $USER` çalıştırıp yeniden giriş yapın.

Python ortamını kurun:

```bash
python3 -m venv --system-site-packages ~/yz
source ~/yz/bin/activate
pip install pyserial smbus2
```

Testleri donanımsız çalıştırın. Sonda `OK` görünmelidir; testteki `--esik-dusuk` hata mesajı beklenen bir davranıştır.

```bash
cd pi
python -m unittest test_egim_alarmi
```

Temel sistemi çalıştırın. Klavyeden `led 1`, `hiz 20` ve `q` komutları kullanılabilir. `alici.py` her çalıştırmada verilen CSV dosyasını sıfırlar; saklanacak kayıtlara farklı ad verin.

```bash
python alici.py --csv olcum.csv
```

Eğim alarmını çalıştırın. Önce `alici.py` kapatılmalıdır, çünkü seri portu aynı anda iki program okuyamaz.

```bash
python egim_alarmi.py
```

LED, ortalama açı 30°'nin üstüne çıkınca yanar, 25°'nin altına inince söner. Olaylar `olcum/egim_olaylari.csv` dosyasına yazılır.

| Seçenek | Varsayılan | Ne yapar |
| --- | --- | --- |
| `--port` | `/dev/serial0` | Seri port |
| `--baud` | 115200 | Baud hızı |
| `--esik-yuksek` | 30 | Alarmın başladığı açı (°) |
| `--esik-dusuk` | 25 | Alarmın bittiği açı (°); yüksek eşiğe eşitse histerezis olmaz |
| `--pencere` | 10 | Ortalamaya giren örnek sayısı |
| `--yazdir` | 50 | Ekrana kaç IMU satırında bir yazılacağı |
| `--sure` | yok | Otomatik durma süresi (s); verilmezse `Ctrl+C` ile durur |
| `--referans` | yok | Açı doğruluğu ölçümündeki gerçek açı (°) |
| `--olay-dosyasi` | `olcum/egim_olaylari.csv` | Olay günlüğü |
| `--aci-dosyasi` | `olcum/aci_dogruluk.csv` | Açı doğruluğu tablosu |

Ölçüm komutları:

```bash
python egim_alarmi.py --referans 45 --sure 30
```

```bash
python egim_alarmi.py --sure 60 --olay-dosyasi ../olcum/histerezisli.csv
```

```bash
python egim_alarmi.py --esik-dusuk 30 --sure 60 --olay-dosyasi ../olcum/histerezissiz.csv
```

## Protokol tablosu

Bağlantı 115200 baud, 8N1'dir. Her satır `$` ile başlar, `*` sonrasında iki haneli XOR checksum gelir ve `\r\n` ile biter. Checksum, `$` ile `*` arasındaki karakterlerden hesaplanır. V1 yeni mesaj eklemez.

| Yön | Mesaj | Anlamı |
| --- | --- | --- |
| ESP32 → Pi | `$IMU,t,ax,ay,az,gx,gy,gz*HH` | t: ms; diğerleri ham sensör değeri (±2 g → 16384 LSB/g; ±250 °/s → 131 LSB/(°/s)) |
| Pi → ESP32 | `$LED,0\|1*HH` | LED'i söndür / yak |
| Pi → ESP32 | `$HIZ,1..100*HH` | ölçüm hızı (Hz) |
| ESP32 → Pi | `$ACK,<komut>,<değer>*HH` | komut uygulandı |
| ESP32 → Pi | `$ERR,<neden>*HH` | BICIM, CHECKSUM, KOMUT veya I2C |

Örnekler: `$LED,1*50`, `$HIZ,20*75`, `$ACK,LED,1*35`.
