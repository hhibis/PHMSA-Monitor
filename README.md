# PHMSA Special Permit Monitor

Şirket bilgisayarı açık olmadan GitHub Actions üzerinde çalışan Federal Register erken uyarı izleyicisi. Python standart kütüphanesi yeterlidir; pip paketi, PHMSA erişimi veya harici sunucu gerektirmez.

## İzlenen bilgiler

SP: **5861, 7026, 7945, 8162, 8495, 10867, 10915, 10945, 10964, 11194, 12955, 20248**.

RIN: **I789** (ilk karakter büyük I), Turkish Technic Inc.; tracking **2026084156**. Kullanıcı tarafından sağlanan son geçerlilik **2027-08-17**, önerilen yenileme tarihi **2027-06-18**. Bu tarihler PHMSA üzerinden canlı doğrulanmaz. Buradaki RIN, tesisin tanımlayıcısıdır; Federal Register'ın Regulatory Identification Number filtresi kullanılmaz.

## Kurulum

1. GitHub'da boş bir repository oluşturun; örneğin `hhibis/phmsa-sp-monitor`. Bu klasörün **içeriğini** repository köküne aktarın. `.github/workflows/phmsa-monitor.yml` dosyasını da ekleyin. Web yüklemesinde gizli `.github` klasörü görünmüyorsa **Add file → Create new file** ile bu tam yolu oluşturup içeriği yapıştırın.
2. Repository **Settings → General → Features → Issues** açık olsun. **Settings → Actions → General** altında Actions'a izin verin. Organizasyon politikası `contents: write` ve `issues: write` yetkilerini engellememeli. Varsayılan dala botun state commit'i gönderebilmesi gerekir; zorunlu PR/branch protection bunu engelliyorsa izinli bir otomasyon düzeni gerekir.
3. **Actions → PHMSA Monitor → Run workflow** seçin. Ek secret gerekmez; GitHub'ın otomatik `GITHUB_TOKEN` değeri kullanılır.
4. İlk başarılı çalışma `BASELINE` üretir ve `state.json` dosyasını otomatik commit eder. Geçmiş kayıtlar için Issue açmaz. `state.json` dosyasını önceden oluşturmayın ve `.gitignore` içine eklemeyin.
5. İkinci manuel çalışmada yeni kayıt yoksa `OK` beklenir. Sonuç dosyasını run sayfasında **Artifacts → phmsa-monitor-result** içinden indirin.

Zamanlama her gün **06:23 UTC / 09:23 Türkiye saati**. Program varsayılan daldan çalışır. GitHub zamanlanmış işleri geciktirebilir; tam saat garantisi yoktur. Public repository'lerde uzun süre etkinlik olmadığında zamanlama devre dışı bırakılabilir; Actions durumunu ara sıra kontrol edin.

## Davranış ve hata güvenliği

- PHMSA kurumu filtresiyle her SP, I789 ve tracking numarası için ayrı tam metin API araması yapar. Her çalışmada API'nin sunduğu tüm geçmişi sayfalayarak tarar; sonradan indekslenen eski yayınları da yeni eşleşme olarak yakalar. API anahtarı gerekmez.
- Arama sonuçları **inceleme adaylarıdır**. `8162-M` gibi tablo içi kayıtlar arama indeksine bağlıdır; sadece belge başlığına bakılmaz. Sayısal eşleşmeler ilgisiz olabilir. Issue içindeki kaynaktan SP tablosunu kontrol edin. İndeksin bulamadığı kayıtlar veya Federal Register'da yayımlanmayan PHMSA değişiklikleri algılanamaz.
- İlk başarılı tarama baseline olur. Sonraki yeni belge numaraları belge başına bir Issue açar. Bir belgenin birden çok SP ile eşleşmesi tek Issue üretir. Aynı belge numarasının sonradan değişen içeriği ayrıca izlenmez.
- RIN için önerilen yenileme ve son geçerlilik tarihinde veya sonraki ilk başarılı çalışmada birer Issue açılır. İlk çalışmada tarihler geçmiş olsa bile baseline sessizdir; hatırlatma ikinci başarılı çalışmada gelir.
- API hatası, eksik sayfalama, bozuk state veya Issue oluşturma hatasında işlem başarısız olur; eski geçerli state korunur. Hata sonucu artifact'e yazılır; GitHub Actions run'ı kırmızı görünür. Hata Issue'su ayrıca açılmaz.
- State yalnızca bütün aramalar ve gerekli bildirimler başarılıysa atomik olarak değiştirilir. Workflow başarılı durumda commit/push yapar. Push başarısızsa run başarısız görünür ve uzak state eski kalır.
- Issue gövdelerindeki sabit işaretler, state push hatasından sonraki tekrar çalışmada açık **ve kapalı** Issue'ların yeniden açılmasını önler. İşaretleri veya Issue'ları silmeyin. Programın eşzamanlı çalışmaları workflow concurrency ile sıralanır.
- `state.json` silmek yeniden baseline oluşturur ve aradaki uyarıları bastırabilir. Bozulma halinde son geçerli sürümü Git geçmişinden geri yükleyin. İzlenen liste/tarih değişikliklerinde bilinçli state geçişi gerekir; program uyumsuz yapılandırmayı sessizce kabul etmez.

## Dosyalar

```text
monitor.py
.github/workflows/phmsa-monitor.yml
tests/test_monitor.py
.gitignore
README.md
state.json                 # İlk başarılı run oluşturur; Git'te korunur
monitor_result.json        # Her run çıktısı; artifact, Git'e eklenmez
```

Yerel test (isteğe bağlı; düzenli çalışma için bilgisayar gerekmez):

```sh
python -m unittest discover -s tests -v
```

Bildirimli yerel çalıştırma için `GH_TOKEN` ve `GITHUB_REPOSITORY=owner/repo` ortam değişkenlerini ayarlayıp `python monitor.py --notify-github` çalıştırın. Tokensız çalıştırma baseline oluşturabilir; sonraki bildirim gerektiren çalışmalarda state'i ilerletmeden durur. Deneme baseline'ını canlı repository'ye taşımayın.

## Daha sonra e-posta

`hibis@thy.com` için doğrudan e-posta gönderimi bu sürümde yoktur. İleride SMTP veya bir e-posta sağlayıcısı eklenebilir; kimlik bilgileri GitHub Actions Secrets'ta tutulmalıdır. GitHub Watch/notification ayarlarıyla alınan Issue e-postaları GitHub hesabının ayarlarına bağlıdır; belirtilen adrese gönderim garantisi değildir.

## Kaynaklar

- [Federal Register API belgesi](https://www.federalregister.gov/developers/documentation/api/v1)
- [GitHub workflow sözdizimi ve izinleri](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)
- [GitHub zamanlanmış Issue oluşturma](https://docs.github.com/en/actions/tutorials/manage-your-work/schedule-issue-creation)

Federal Register erken uyarı kaynağıdır; resmi izin geçerlilik teyidi ve tesisin yenileme takibinin yerine geçmez.
