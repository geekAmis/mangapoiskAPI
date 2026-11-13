import { Link } from 'react-router-dom';
import { LegalCallout, LegalLayout, LegalList, LegalSection } from '../components/legal/LegalLayout';
import { LegalValue } from '../components/legal/LegalValue';
import { LEGAL_CONFIG, legalPage } from '../lib/legal';
import { useLegalSeo } from '../lib/legalPage';

const PAGE = legalPage('/contacts');

export default function ContactsPage() {
  useLegalSeo(
    PAGE,
    'Контакты и реквизиты владельца MangaPoisk Reborn: email для обращений, жалоб правообладателей и вопросов о персональных данных.',
  );

  return (
    <LegalLayout
      title={PAGE.title}
      intro="Здесь указаны владелец сервиса и каналы связи. Перед публичным запуском владелец обязан заполнить реальные данные — сейчас незаполненные поля явно помечены."
    >
      <LegalCallout title="Перед публичным запуском" tone="warning">
        Контактный email, имя владельца и юрисдикция задаются при сборке через
        переменные <code>LEGAL_CONTACT_EMAIL</code>,{' '}
        <code>LEGAL_OWNER_NAME</code> и <code>LEGAL_JURISDICTION</code>. Если
        поле не заполнено, страница показывает заглушку, а не вымышленный адрес.
        Владелец заполняет эти значения при сборке сайта.
      </LegalCallout>

      <LegalSection id="operator" title="1. Владелец и оператор">
        <dl className="legal-facts">
          <dt>Владелец / оператор</dt>
          <dd>
            <LegalValue value={LEGAL_CONFIG.ownerName} envKey="LEGAL_OWNER_NAME" />
          </dd>
          <dt>Контактный email</dt>
          <dd>
            <LegalValue
              value={LEGAL_CONFIG.contactEmail}
              envKey="LEGAL_CONTACT_EMAIL"
              email
            />
          </dd>
          <dt>Юрисдикция</dt>
          <dd>
            <LegalValue
              value={LEGAL_CONFIG.jurisdiction}
              envKey="LEGAL_JURISDICTION"
            />
          </dd>
          <dt>Сайт</dt>
          <dd>MangaPoisk Reborn</dd>
        </dl>
        <p>
          Если для вашей юрисдикции обязательны полное юридическое название,
          регистрационный номер или почтовый адрес, владелец должен добавить их
          на эту страницу до публичного запуска. Текущая редакция не выдумывает
          реквизиты.
        </p>
      </LegalSection>

      <LegalSection id="channels" title="2. Как связаться">
        <p>
          Основной канал связи — email{' '}
          <LegalValue
            value={LEGAL_CONFIG.contactEmail}
            envKey="LEGAL_CONTACT_EMAIL"
            email
          />. Укажите в теме письма одну из тем, чтобы обращение попало к
          нужному человеку:
        </p>
        <LegalList>
          <li>«Правообладателям / DMCA» — жалобы на контент и ссылки;</li>
          <li>«Персональные данные» — доступ, исправление, удаление аккаунта;</li>
          <li>«Безопасность» — уязвимости и инциденты;</li>
          <li>«Общий вопрос» — всё остальное.</li>
        </LegalList>
      </LegalSection>

      <LegalSection id="timeline" title="3. Сроки ответа">
        <p>
          Мы стараемся отвечать на обычные обращения в течение 3 рабочих дней, на
          жалобы правообладателей — в сроки, указанные на странице{' '}
          <Link to="/dmca">DMCA</Link>. Запросы по персональным данным
          рассматриваются в срок, установленный законом; ориентир — до 30 дней.
        </p>
      </LegalSection>

      <LegalSection id="complaints" title="4. Жалобы правообладателей">
        <p>
          Для жалоб на контент используйте процедуру на странице{' '}
          <Link to="/dmca">«Правообладателям и DMCA»</Link>: там перечислены
          необходимые данные и сроки. Письмо без ссылок и подтверждения прав
          может потребовать уточнений.
        </p>
      </LegalSection>

      <LegalSection id="privacy" title="5. Персональные данные">
        <p>
          Какие данные обрабатываются, сколько хранятся и как удалить аккаунт,
          описано в <Link to="/privacy">Политике конфиденциальности</Link>. Для
          удаления аккаунта напишите с зарегистрированного email с темой
          «Удаление аккаунта».
        </p>
      </LegalSection>

      <LegalSection id="disclaimer" title="6. Важное уточнение">
        <p>
          MangaPoisk Reborn — агрегатор метаданных и ссылок. Мы не храним
          исходные файлы глав и не являемся правообладателем произведений.
          Контакты на этой странице предназначены для связи с оператором сайта,
          а не с авторами или издателями.
        </p>
      </LegalSection>
    </LegalLayout>
  );
}
