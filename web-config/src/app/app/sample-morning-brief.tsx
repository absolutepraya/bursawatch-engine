export function SampleMorningBrief() {
  return (
    <section className="sample-morning-brief" aria-labelledby="sample-morning-brief-title">
      <div className="sample-morning-brief-heading">
        <div>
          <h2 id="sample-morning-brief-title">BURSAWATCH PAGI</h2>
          <p>Mon, 5 Oct 2026</p>
        </div>
        <span>Example only · dummy figures</span>
      </div>
      <p>
        <strong>IHSG: tunggu konfirmasi pemulihan.</strong> Pergerakan di atas 6.100 membuka ruang
        pemulihan, sementara kehilangan 6.000 mengembalikan tekanan.
      </p>
      <div className="sample-rotation-grid">
        <section aria-labelledby="sample-sector-rotation">
          <h3 id="sample-sector-rotation">ROTASI SEKTOR</h3>
          <ul>
            <li>Energy · Leading: kekuatan relatif +2,3 pp; momentum +1,1 pp.</li>
            <li>Financials · Improving: kekuatan relatif -0,6 pp; momentum +0,9 pp.</li>
            <li>Technology · Weakening: kekuatan relatif +1,6 pp; momentum -0,8 pp.</li>
          </ul>
        </section>
        <section aria-labelledby="sample-konglo-rotation">
          <h3 id="sample-konglo-rotation">ROTASI KONGLO</h3>
          <ul>
            <li>Barito · Leading: kekuatan relatif +2,5 pp; momentum +1,4 pp.</li>
            <li>Djarum · Improving: kekuatan relatif -0,5 pp; momentum +1,1 pp.</li>
            <li>Astra / Jardine · Weakening: kekuatan relatif +1,7 pp; momentum -0,9 pp.</li>
          </ul>
        </section>
      </div>
    </section>
  );
}
