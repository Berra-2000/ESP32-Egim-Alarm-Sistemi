#!/usr/bin/env python3
"""V1 - Egim alarmi.

ESP32'den gelen $IMU satirlarindan egim acisini hesaplar. Aci esigi asinca
$LED,1, geri donunce $LED,0 gonderir; olaylari ayri bir dosyaya kaydeder.

Ornekler:
    python egim_alarmi.py                                  # 30 / 25 derece
    python egim_alarmi.py --esik-yuksek 40 --esik-dusuk 35
    python egim_alarmi.py --esik-dusuk 30 --sure 60        # histerezissiz
    python egim_alarmi.py --referans 45 --sure 30          # aci dogrulugu
"""
import argparse
import csv
import math
import statistics
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from protokol import coz, kodla

OLCUM_KLASORU = Path(__file__).resolve().parent.parent / "olcum"


def satir_coz(ham):
    """Seri porttan gelen baytlari cozer; satir bozuksa None.

    coz() metin ister; ASCII disi bayt iceren satir bozuk sayilir.
    """
    try:
        return coz(ham.decode("ascii"))
    except UnicodeDecodeError:
        return None


def imu_aci(alanlar):
    """IMU alanlarindan (t_ms, aci_derece) dondurur; alanlar bozuksa None.

    ax ve az ayni olcekte oldugu icin oranlari g'ye cevirmeden kullanilabilir.
    """
    if len(alanlar) != 8:
        return None
    try:
        t_ms, ax, az = int(alanlar[1]), int(alanlar[2]), int(alanlar[4])
    except ValueError:
        return None
    return t_ms, math.degrees(math.atan2(ax, az))


class EgimAlarmi:
    """Kayan ortalama ve histerezisli esik. Iki esik esitse histerezis yoktur."""

    def __init__(self, esik_yuksek, esik_dusuk, pencere=10):
        self.esik_yuksek = esik_yuksek
        self.esik_dusuk = esik_dusuk
        self.acilar = deque(maxlen=pencere)
        self.aktif = False
        self.ortalama = None

    def guncelle(self, aci):
        """Yeni aciyi isler; durum degistiyse True dondurur."""
        self.acilar.append(aci)
        if len(self.acilar) < self.acilar.maxlen:
            return False  # pencere dolmadan karar verme
        self.ortalama = sum(self.acilar) / len(self.acilar)
        if not self.aktif and self.ortalama > self.esik_yuksek:
            self.aktif = True
            return True
        if self.aktif and self.ortalama < self.esik_dusuk:
            self.aktif = False
            return True
        return False


def olay_yaz(yol, t_ms, olay, aci):
    """Alarm olayini zaman damgasiyla dosyaya ekler."""
    yeni_dosya = not yol.exists()
    with open(yol, "a", newline="", encoding="utf-8") as dosya:
        yazici = csv.writer(dosya)
        if yeni_dosya:
            yazici.writerow(["zaman", "esp_t_ms", "olay", "aci_derece"])
        yazici.writerow([datetime.now().isoformat(timespec="milliseconds"),
                         t_ms, olay, f"{aci:.2f}"])


def aci_kaydi_yaz(yol, referans, acilar):
    """Aci dogrulugu tablosuna bir satir ekler ve satiri ekrana yazar."""
    ortalama = statistics.fmean(acilar)
    sapma = statistics.stdev(acilar) if len(acilar) > 1 else 0.0
    yeni_dosya = not yol.exists()
    with open(yol, "a", newline="", encoding="utf-8") as dosya:
        yazici = csv.writer(dosya)
        if yeni_dosya:
            yazici.writerow(["referans_derece", "olculen_ortalama", "std_sapma",
                             "hata_derece", "ornek_sayisi"])
        yazici.writerow([referans, f"{ortalama:.2f}", f"{sapma:.2f}",
                         f"{ortalama - referans:.2f}", len(acilar)])
    print(f"Referans {referans} derece -> olculen {ortalama:.2f} "
          f"(std {sapma:.2f}, hata {ortalama - referans:+.2f})")


def calistir(seri, ayarlar):
    """Satirlari okur, alarmi isletir ve sayaclari dondurur."""
    alarm = EgimAlarmi(ayarlar.esik_yuksek, ayarlar.esik_dusuk, ayarlar.pencere)
    sayac = {"gecerli": 0, "hatali": 0, "led_degisim": 0,
             "komut": 0, "ack": 0, "err": 0}
    tum_acilar = []

    # ESP32'de LED onceki calismadan yanik kalmis olabilir: baslangicta esitle.
    seri.write(kodla("LED", 0))
    sayac["komut"] += 1

    baslangic = time.monotonic()
    try:
        while ayarlar.sure is None or time.monotonic() - baslangic < ayarlar.sure:
            ham = seri.readline()
            if not ham:  # zaman asimi: satir gelmedi
                continue
            alanlar = satir_coz(ham)
            if alanlar is None:
                sayac["hatali"] += 1
                continue
            if alanlar[0] == "ACK":
                sayac["ack"] += 1
            elif alanlar[0] == "ERR":
                sayac["err"] += 1
                print("ESP32 hatasi:", ",".join(alanlar[1:]))
            elif alanlar[0] == "IMU":
                imu = imu_aci(alanlar)
                if imu is None:
                    sayac["hatali"] += 1
                    continue
                sayac["gecerli"] += 1
                t_ms, aci = imu
                tum_acilar.append(aci)

                if alarm.guncelle(aci):
                    seri.write(kodla("LED", int(alarm.aktif)))
                    sayac["komut"] += 1
                    sayac["led_degisim"] += 1
                    olay = "ALARM_BASLADI" if alarm.aktif else "ALARM_BITTI"
                    olay_yaz(ayarlar.olay_dosyasi, t_ms, olay, alarm.ortalama)
                    print(f"{olay}: {alarm.ortalama:.1f} derece")

                if alarm.ortalama is not None and sayac["gecerli"] % ayarlar.yazdir == 0:
                    durum = "ALARM" if alarm.aktif else "normal"
                    print(f"aci={alarm.ortalama:6.1f}  {durum}  "
                          f"gecerli={sayac['gecerli']}  hatali={sayac['hatali']}")
    except KeyboardInterrupt:
        pass

    gecen = time.monotonic() - baslangic
    sayac["ornek_hizi"] = sayac["gecerli"] / gecen if gecen > 0 else 0.0
    if ayarlar.referans is not None and tum_acilar:
        aci_kaydi_yaz(ayarlar.aci_dosyasi, ayarlar.referans, tum_acilar)
    return sayac


def arguman_oku(argumanlar=None):
    ayristirici = argparse.ArgumentParser(description="V1 - Egim alarmi")
    ayristirici.add_argument("--port", default="/dev/serial0")
    ayristirici.add_argument("--baud", type=int, default=115200)
    ayristirici.add_argument("--esik-yuksek", type=float, default=30.0,
                             help="bu acinin ustunde alarm baslar (derece)")
    ayristirici.add_argument("--esik-dusuk", type=float, default=25.0,
                             help="bu acinin altinda alarm biter; yuksek esige "
                                  "esitse histerezis olmaz (derece)")
    ayristirici.add_argument("--pencere", type=int, default=10,
                             help="ortalamaya giren ornek sayisi")
    ayristirici.add_argument("--yazdir", type=int, default=50,
                             help="ekrana kac IMU satirinda bir yazilacagi")
    ayristirici.add_argument("--sure", type=float,
                             help="saniye; verilmezse Ctrl+C ile durur")
    ayristirici.add_argument("--referans", type=float,
                             help="aci dogrulugu olcumu icin sabitlenen gercek aci")
    ayristirici.add_argument("--olay-dosyasi", type=Path,
                             default=OLCUM_KLASORU / "egim_olaylari.csv")
    ayristirici.add_argument("--aci-dosyasi", type=Path,
                             default=OLCUM_KLASORU / "aci_dogruluk.csv")
    ayarlar = ayristirici.parse_args(argumanlar)
    if ayarlar.esik_dusuk > ayarlar.esik_yuksek:
        ayristirici.error("--esik-dusuk, --esik-yuksek degerinden buyuk olamaz")
    if ayarlar.pencere < 1 or ayarlar.yazdir < 1:
        ayristirici.error("--pencere ve --yazdir en az 1 olmali")
    return ayarlar


def main():
    import serial  # pyserial yalnizca gercek portta gerekir

    ayarlar = arguman_oku()
    ayarlar.olay_dosyasi.parent.mkdir(parents=True, exist_ok=True)
    ayarlar.aci_dosyasi.parent.mkdir(parents=True, exist_ok=True)
    with serial.Serial(ayarlar.port, ayarlar.baud, timeout=0.5) as seri:
        sayac = calistir(seri, ayarlar)
    print(f"\nGecerli satir : {sayac['gecerli']} ({sayac['ornek_hizi']:.1f} ornek/s)")
    print(f"Hatali satir  : {sayac['hatali']}")
    print(f"LED degisimi  : {sayac['led_degisim']}")
    print(f"Komut / ACK / ERR: {sayac['komut']} / {sayac['ack']} / {sayac['err']}")


if __name__ == "__main__":
    main()
