import type {
  DecisionListPage,
  DraftListPage,
  PublicationPage,
  QaReportListPage,
  ReviewListPage,
  WorkItemDetail,
} from "@/lib/editorial-api";

// "Şimdi ne yapmalı": ONE next step derived from durable facts only — the
// current workflow state plus the latest artifacts. It never invents a
// state; where the machine is in the middle of a transition it says so.
// `sectionId` names the detail section that holds the matching command,
// so the page can open that section first and fold the rest.

export type NextStep = {
  key: string;
  title: string;
  detail: string;
  sectionId: string;
  // true when the operator must act; false when the machine is working or
  // the item is terminal.
  actionable: boolean;
  // The step's command needs a configured AI provider of this kind.
  needsAi?: "text" | "image";
};

export type NextStepInput = {
  detail: WorkItemDetail;
  drafts: DraftListPage | null;
  reviews: ReviewListPage | null;
  qaReports: QaReportListPage | null;
  decisions: DecisionListPage | null;
  media: { total_needs: number; satisfied_needs: number } | null;
  publication: PublicationPage | null;
  isReviewer: boolean;
};

function latestByVersion<T extends { version: number }>(rows: T[]): T | null {
  return rows.reduce<T | null>(
    (best, row) => (best === null || row.version > best.version ? row : best),
    null,
  );
}

const MACHINE_STAGES: Record<string, string> = {
  discovered: "Kaynak keşfedildi; getirme ve normalizasyon otomatik sürüyor.",
  researching: "Araştırma girdisi işleniyor; otomatik aşama.",
  normalized: "İçerik normalize edildi; kopya kontrolü otomatik sürüyor.",
  duplicate_check: "Kopya kontrolü otomatik sürüyor.",
  duplicate: "Kopya olarak işaretlendi; bu öğe üzerinde iş yok.",
};

export function nextStep(input: NextStepInput): NextStep {
  const { detail } = input;
  const state = detail.work_item.current_state;
  const opportunity = detail.opportunity;

  if (state === "blocked") {
    return {
      key: "blocked",
      title: "Engeli çöz",
      detail:
        detail.work_item.blocked_reason !== null
          ? `Engel nedeni: ${detail.work_item.blocked_reason}. Engeli çözün ya da öğeyi reddedin.`
          : "İş öğesi engellendi; engeli çözün ya da öğeyi reddedin.",
      sectionId: "detail-workflow",
      actionable: true,
    };
  }
  if (state === "rejected") {
    return {
      key: "rejected",
      title: "Reddedildi",
      detail:
        detail.work_item.rejected_reason !== null
          ? `Ret gerekçesi: ${detail.work_item.rejected_reason}. Başka bir adım yok.`
          : "Bu iş öğesi reddedildi; başka bir adım yok.",
      sectionId: "detail-workflow",
      actionable: false,
    };
  }
  if (state in MACHINE_STAGES) {
    return {
      key: "machine",
      title: "Makine çalışıyor",
      detail: MACHINE_STAGES[state]!,
      sectionId: "detail-workflow",
      actionable: false,
    };
  }

  if (state === "idea_scoring") {
    if (opportunity === null) {
      return {
        key: "no-opportunity",
        title: "Fırsat yok",
        detail: "Bu iş öğesine bağlı bir fırsat kaydı yok.",
        sectionId: "detail-opportunity",
        actionable: false,
      };
    }
    if (opportunity.disposition !== "open") {
      return {
        key: "disposed",
        title: "Fırsat kararı verildi",
        detail: "Fırsat artık açık değil; iş akışı geçişi bekleniyor.",
        sectionId: "detail-opportunity",
        actionable: false,
      };
    }
    if (detail.scores.length === 0) {
      return {
        key: "evaluate",
        title: "Değerlendirmeyi kuyruğa al",
        detail:
          "Kaynak tabanı henüz puanlanmadı. Skor olmadan görevlendirme yapılamaz; önce değerlendirmeyi çalıştırın.",
        sectionId: "detail-opportunity",
        actionable: true,
      };
    }
    if (opportunity.commission_eligible) {
      return {
        key: "commission",
        title: "Üretim kararı ver",
        detail:
          "Kaynak tabanı görevlendirilebilir. Gerekçeyle görevlendirin ya da reddedin.",
        sectionId: "detail-opportunity",
        actionable: true,
      };
    }
    if (opportunity.commission_override_possible) {
      return {
        key: "commission-override",
        title: "Üretim kararı ver (kaynak tabanı zayıf)",
        detail:
          "Skor görevlendirilebilir değil; konu buna değiyorsa gerekçeyle yine de görevlendirin, değmiyorsa reddedin.",
        sectionId: "detail-opportunity",
        actionable: true,
      };
    }
    return {
      key: "decide",
      title: "Fırsatı reddet ya da yeniden değerlendir",
      detail: "Bu fırsat görevlendirilemez durumda.",
      sectionId: "detail-opportunity",
      actionable: true,
    };
  }

  if (state === "evidence_building") {
    if (detail.ideas.length === 0) {
      return {
        key: "generate-ideas",
        needsAi: "text",
        title: "Fikir adayları üret",
        detail:
          "Görevlendirilen fırsat için henüz fikir yok. Aday sayısını seçip üretimi kuyruğa alın; sonuç geldiğinde birini seçeceksiniz.",
        sectionId: "detail-ideas",
        actionable: true,
      };
    }
    if (detail.effective_selected_idea_id === null) {
      return {
        key: "select-idea",
        title: "Bir fikir seç",
        detail:
          "Adaylar hazır. Üretilecek fikri gerekçeyle seçin; kanıt paketi seçili fikirden oluşur.",
        sectionId: "detail-ideas",
        actionable: true,
      };
    }
    const pack = latestByVersion(detail.evidence_packs);
    if (pack === null) {
      return {
        key: "build-pack",
        title: "Kanıt paketi oluştur",
        detail:
          "Seçili fikir için uygun kanıt satırlarını işaretleyip paketi oluşturun. Paket Hazır çıkarsa SEO araştırmasına otomatik geçer.",
        sectionId: "detail-evidence",
        actionable: true,
      };
    }
    if (pack.sufficiency === "ready") {
      return {
        key: "pack-ready",
        title: "Paket hazır, aşama geçişi bekleniyor",
        detail:
          "Kanıt paketi Hazır. Sistem SEO araştırmasına geçiriyor; sayfayı yenileyin.",
        sectionId: "detail-evidence",
        actionable: false,
      };
    }
    if (pack.sufficiency === "conflicted") {
      return {
        key: "pack-conflicted",
        title: "Kanıt çelişkisini çöz",
        detail:
          "Paket çelişkili. Çelişkiyi gerekçeyle çözüp paketi yeni sürüm olarak yeniden birleştirin.",
        sectionId: "detail-evidence",
        actionable: true,
      };
    }
    return {
      key: "pack-insufficient",
      title: "Kanıt yetersiz",
      detail:
        "Paket yeterli değil. Yeni araştırma girdisi ekleyin ya da daha fazla kanıt seçip yeni sürüm olarak yeniden birleştirin.",
      sectionId: "detail-evidence",
      actionable: true,
    };
  }

  if (state === "seo_research") {
    if (detail.intent_analyses.length === 0) {
      return {
        key: "intent",
        needsAi: "text",
        title: "Arama niyeti analizini kuyruğa al",
        detail: "Analiz tamamlanınca sistem Brif hazırlığına geçirir.",
        sectionId: "detail-intent",
        actionable: true,
      };
    }
    return {
      key: "intent-wait",
      title: "Analiz kuyrukta",
      detail:
        "Arama niyeti analizi var; sistem Brif hazırlığına geçiriyor. Sayfayı yenileyin.",
      sectionId: "detail-intent",
      actionable: false,
    };
  }

  if (state === "briefing") {
    const brief = latestByVersion(detail.briefs);
    if (brief === null) {
      return {
        key: "brief",
        needsAi: "text",
        title: "Taslak brief oluştur",
        detail: "Kanıt ve niyet analizinden brief oluşturun.",
        sectionId: "detail-briefs",
        actionable: true,
      };
    }
    if (brief.status === "draft") {
      return {
        key: "accept-brief",
        title: "Brifi taslak için kabul et",
        detail: "Brief hazır. Kabul edince iş öğesi Taslak yazımına geçer.",
        sectionId: "detail-briefs",
        actionable: true,
      };
    }
    return {
      key: "brief-accepted",
      title: "Brief kabul edildi",
      detail: "Sistem Taslak yazımına geçiriyor; sayfayı yenileyin.",
      sectionId: "detail-briefs",
      actionable: false,
    };
  }

  if (state === "drafting" || state === "changes_requested") {
    const active = input.drafts?.drafts.some((row) => row.status === "active");
    if (state === "changes_requested") {
      return {
        key: "rework",
        title: "Yeniden çalışmayı yönlendir",
        detail:
          "Değişiklik istendi. Sorumlu aşamayı seçip yeniden çalışmayı yönlendirin.",
        sectionId: "detail-drafts",
        actionable: true,
      };
    }
    if (!active) {
      return {
        key: "draft",
        needsAi: "text",
        title: "Yazar taslağı üret",
        detail:
          "Kabul edilmiş brief'ten taslak üretin ya da operatör taslağı gönderin.",
        sectionId: "detail-drafts",
        actionable: true,
      };
    }
    return {
      key: "draft-wait",
      title: "Taslak var",
      detail: "Etkin taslak mevcut; sistem Editör incelemesine geçiriyor.",
      sectionId: "detail-drafts",
      actionable: false,
    };
  }

  if (state === "editing") {
    const review = input.reviews?.reviews.find(
      (row) => row.status === "active",
    );
    if (review === undefined) {
      return {
        key: "review",
        needsAi: "text",
        title: "Editör değerlendirmesi üret",
        detail: "Etkin taslak için editör değerlendirmesi üretin.",
        sectionId: "detail-reviews",
        actionable: true,
      };
    }
    if (review.verdict === "pass") {
      return {
        key: "accept-review",
        title: "Değerlendirmeyi kabul et",
        detail: "Editör Geçti dedi. Kabul edince Kalite kontrolüne geçer.",
        sectionId: "detail-reviews",
        actionable: true,
      };
    }
    return {
      key: "review-revise",
      title: "Yeniden çalışma iste",
      detail:
        "Editör Düzelt dedi. Taslağı yeniden çalışmaya gönderin ya da bulguları inceleyip değerlendirmeyi kabul edin.",
      sectionId: "detail-reviews",
      actionable: true,
    };
  }

  if (state === "qa_review") {
    const report = input.qaReports?.reports.find(
      (row) => row.status === "active",
    );
    if (report === undefined) {
      return {
        key: "qa",
        title: "QA kapılarını çalıştır",
        detail: "Kabul edilmiş taslak için kalite kapılarını çalıştırın.",
        sectionId: "detail-qa",
        actionable: true,
      };
    }
    if (report.outcome === "not_ready") {
      const media = input.media;
      const mediaOpen =
        media !== null && media.satisfied_needs < media.total_needs;
      return {
        key: "qa-not-ready",
        needsAi: mediaOpen ? "image" : undefined,
        title: mediaOpen
          ? "Görsel ihtiyaçlarını karşıla"
          : "QA kapıları geçmedi",
        detail: mediaOpen
          ? `${media.total_needs - media.satisfied_needs} görsel ihtiyacı açık. Görsel yükleyin ya da üretin, sonra QA kapılarını yeniden çalıştırın.`
          : "Rapor Hazır değil dedi. Bulguları inceleyip yeniden çalışma isteyin ya da uygun kapıyı gerekçeyle atlayın.",
        sectionId: mediaOpen ? "detail-media" : "detail-qa",
        actionable: true,
      };
    }
    return {
      key: "qa-ready",
      title: "Kalite kontrolü geçti",
      detail: "Sistem İnsan onayına geçiriyor; sayfayı yenileyin.",
      sectionId: "detail-qa",
      actionable: false,
    };
  }

  if (state === "awaiting_human_review") {
    return input.isReviewer
      ? {
          key: "decide-final",
          title: "Nihai kararı ver",
          detail:
            "Paket onay bekliyor: onaylayın, değişiklik isteyin ya da reddedin. Bu karar adınızla kaydedilir.",
          sectionId: "detail-decisions",
          actionable: true,
        }
      : {
          key: "reviewer-needed",
          title: "İnceleyici kararı bekleniyor",
          detail: "Bu adım inceleyici rolü gerektirir; hesabınızda bu rol yok.",
          sectionId: "detail-decisions",
          actionable: false,
        };
  }

  if (state === "approved") {
    const packages = input.publication?.packages ?? [];
    return packages.length === 0
      ? {
          key: "assemble",
          title: "Yayın paketini oluştur",
          detail: "Onaylı paket için yayın paketini birleştirin.",
          sectionId: "detail-publication",
          actionable: true,
        }
      : {
          key: "schedule",
          title: "Yayını zamanla",
          detail: "Yayın paketi hazır; yayın zamanını belirleyin.",
          sectionId: "detail-publication",
          actionable: true,
        };
  }
  if (state === "approval_expired") {
    return {
      key: "approval-expired",
      title: "Onay süresi doldu",
      detail: "Durumu çözün: yeniden onaya gönderin ya da geri yönlendirin.",
      sectionId: "detail-decisions",
      actionable: true,
    };
  }
  if (state === "scheduled") {
    return {
      key: "publish",
      title: "Yayınla",
      detail: "Zamanlanmış paket için yayını başlatın.",
      sectionId: "detail-publication",
      actionable: true,
    };
  }
  if (state === "publishing") {
    return {
      key: "publishing",
      title: "Yayın deneniyor",
      detail: "Yayın API'sine gönderim sürüyor; deneme sonuçlarını izleyin.",
      sectionId: "detail-publication",
      actionable: false,
    };
  }
  if (state === "published") {
    return {
      key: "published",
      title: "Yayınlandı",
      detail: "İçerik yayında; bu öğe üzerinde başka adım yok.",
      sectionId: "detail-publication",
      actionable: false,
    };
  }
  return {
    key: "unknown",
    title: "Durum tanınmadı",
    detail: `İş akışı durumu: ${state}.`,
    sectionId: "detail-workflow",
    actionable: false,
  };
}
