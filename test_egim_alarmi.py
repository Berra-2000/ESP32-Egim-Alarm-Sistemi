"""Donanim gerektirmeyen testler: python -m unittest test_egim_alarmi"""
import csv
import math
import random
import tempfile
import unittest
from pathlib import Path

import egim_alarmi as ea
from protokol import kodla

G = 16384  # +-2 g araliginda 1 g


def imu_satiri(aci, t_ms=0):
    """Verilen aciya karsilik gelen gecerli bir $IMU satiri uretir."""
    ax = round(G * math.sin(math.radians(aci)))
    az = round(G * math.cos(math.radians(aci)))
    return kodla("IMU", t_ms, ax, 0, az, 0, 0, 0)


class SahteSeri:
    """Verilen satirlari sirayla okutur, yazilanlari biriktirir."""

    def __init__(self, satirlar):
        self.satirlar = iter(satirlar)
        self.yazilan = []

    def write(self, veri):
        self.yazilan.append(veri)

    def readline(self):
        try:
            return next(self.satirlar)
        except StopIteration:
            raise KeyboardInterrupt  # calistir() Ctrl+C gibi temiz biter


class ProtokolTesti(unittest.TestCase):
    def test_slaytlardaki_checksum_ornekleri(self):
        self.assertEqual(kodla("LED", 1), b"$LED,1*50\r\n")
        self.assertEqual(kodla("HIZ", 20), b"$HIZ,20*75\r\n")
        self.assertEqual(kodla("ACK", "LED", 1), b"$ACK,LED,1*35\r\n")

    def test_slayttaki_imu_satiri(self):
        alanlar = ea.satir_coz(b"$IMU,1520,-312,85,16420,-41,12,-7*6B\r\n")
        t_ms, aci = ea.imu_aci(alanlar)
        self.assertEqual(t_ms, 1520)
        self.assertAlmostEqual(aci, math.degrees(math.atan2(-312, 16420)))

    def test_bozuk_satirlar_reddedilir(self):
        for ham in (b"$LED,1*51\r\n", b"LED,1*50\r\n", b"$LED,1\r\n",
                    b"$LED,1*ZZ\r\n", b"$LED,1*5\r\n", b"\xff\xfe\r\n", b"\r\n"):
            self.assertIsNone(ea.satir_coz(ham), ham)

    def test_bilinen_acilar(self):
        for aci in (0, 45, 90):
            alanlar = ea.satir_coz(imu_satiri(aci, 1000))
            t_ms, sonuc = ea.imu_aci(alanlar)
            self.assertEqual(t_ms, 1000)
            self.assertAlmostEqual(sonuc, aci, places=2)

    def test_eksik_veya_bozuk_imu_alanlari(self):
        self.assertIsNone(ea.imu_aci(["IMU", "1", "2"]))
        self.assertIsNone(ea.imu_aci(["IMU", "1", "x", "0", "0", "0", "0", "0"]))


class AlarmTesti(unittest.TestCase):
    def test_pencere_dolmadan_karar_verilmez(self):
        alarm = ea.EgimAlarmi(30, 25, pencere=10)
        for _ in range(9):
            self.assertFalse(alarm.guncelle(90))
        self.assertTrue(alarm.guncelle(90))
        self.assertTrue(alarm.aktif)

    def test_histerezis_bandinda_durum_korunur(self):
        alarm = ea.EgimAlarmi(30, 25, pencere=1)
        self.assertTrue(alarm.guncelle(31))
        self.assertFalse(alarm.guncelle(27))  # bant icinde: hala alarm
        self.assertTrue(alarm.aktif)
        self.assertTrue(alarm.guncelle(24))
        self.assertFalse(alarm.aktif)
        self.assertFalse(alarm.guncelle(27))  # bant icinde: hala normal
        self.assertFalse(alarm.aktif)

    def test_histerezis_titremeyi_azaltir(self):
        rastgele = random.Random(1)
        acilar = [30 + rastgele.gauss(0, 1) for _ in range(1000)]

        def degisim(esik_dusuk):
            alarm = ea.EgimAlarmi(30, esik_dusuk, pencere=1)
            return sum(alarm.guncelle(aci) for aci in acilar)

        self.assertGreater(degisim(30), 100)  # histerezissiz: surekli titrer
        self.assertLessEqual(degisim(25), 1)


class UctanUcaTesti(unittest.TestCase):
    def setUp(self):
        gecici = tempfile.TemporaryDirectory()
        self.addCleanup(gecici.cleanup)
        self.klasor = Path(gecici.name)

    def ayarlar(self, *ek):
        return ea.arguman_oku([
            "--olay-dosyasi", str(self.klasor / "olaylar.csv"),
            "--aci-dosyasi", str(self.klasor / "aci.csv"),
            "--pencere", "1", *ek])

    def test_komut_yalnizca_durum_degisince_gider(self):
        satirlar = ([imu_satiri(40)] * 5 + [imu_satiri(10)] * 5
                    + [b"$IMU,bozuk*00\r\n", kodla("ACK", "LED", 1)])
        seri = SahteSeri(satirlar)
        sayac = ea.calistir(seri, self.ayarlar())

        # Ilk komut baslangic esitlemesi, sonra yalnizca iki durum degisimi.
        self.assertEqual(seri.yazilan,
                         [b"$LED,0*51\r\n", b"$LED,1*50\r\n", b"$LED,0*51\r\n"])
        self.assertEqual(sayac["gecerli"], 10)
        self.assertEqual(sayac["hatali"], 1)
        self.assertEqual(sayac["led_degisim"], 2)
        self.assertEqual(sayac["ack"], 1)

        with open(self.klasor / "olaylar.csv", encoding="utf-8") as dosya:
            olaylar = [satir["olay"] for satir in csv.DictReader(dosya)]
        self.assertEqual(olaylar, ["ALARM_BASLADI", "ALARM_BITTI"])

    def test_aci_dogrulugu_kaydi(self):
        seri = SahteSeri([imu_satiri(45)] * 20)
        ea.calistir(seri, self.ayarlar("--referans", "45"))
        with open(self.klasor / "aci.csv", encoding="utf-8") as dosya:
            satir = next(csv.DictReader(dosya))
        self.assertEqual(satir["ornek_sayisi"], "20")
        self.assertAlmostEqual(float(satir["hata_derece"]), 0, places=1)

    def test_ters_esikler_reddedilir(self):
        with self.assertRaises(SystemExit):
            ea.arguman_oku(["--esik-yuksek", "20", "--esik-dusuk", "25"])


if __name__ == "__main__":
    unittest.main()
