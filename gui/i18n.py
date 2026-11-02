from __future__ import annotations

LANGS = ('ru', 'en')
_lang = 'ru'
_idx = 0

STRINGS = {
    'app.name': ('tg-ws-turn-proxy', 'tg-ws-turn-proxy'),
    'pill.proxy': ('Прокси', 'Proxy'),
    'pill.calls': ('Звонки', 'Calls'),
    'pill.winws': ('winws', 'winws'),
    'btn.connect': ('Подключить', 'Connect'),
    'btn.settings': ('Настройки', 'Settings'),
    'btn.start': ('Запустить', 'Start'),
    'btn.stop': ('Остановить', 'Stop'),
    'btn.clear': ('Очистить', 'Clear'),
    'btn.back': ('Назад', 'Back'),
    'btn.next': ('Далее', 'Next'),
    'btn.retry': ('Повторить', 'Retry'),
    'btn.copy': ('Копировать', 'Copy'),
    'btn.copied': ('Скопировано', 'Copied'),
    'btn.save': ('Сохранить', 'Save'),
    'btn.cancel': ('Отмена', 'Cancel'),
    'btn.refresh': ('Обновить', 'Refresh'),
    'btn.minimize': ('Свернуть', 'Minimize'),
    'btn.close': ('Закрыть', 'Close'),

    'step.of': ('Шаг {n} из {m}', 'Step {n} of {m}'),
    'lang.ru': ('Русский', 'Russian'),
    'lang.en': ('English', 'English'),

    'boot.title': ('Запуск профиля winws (zapret)',
                   'Starting the winws profile (zapret)'),
    'boot.desc': ('Сначала запускается отдельная стратегия winws с фильтрами, которые '
                  'открывают дорогу до Cloudflare и пропускают мимо релея '
                  'прямой STUN. Если своя рабочая стратегия zapret уже есть и запущена, '
                  'то этот шаг ничего не меняет.\n'
                  'Однако стоит добавить в свою стратегию нужные фильтры '
                  '(если их нет), иначе воркеры и звонки могут не работать.\n'
                  'Какие именно фильтры нужно добавить в свою стратегию '
                  'описано в README этого проекта.',
                  'First, a separate winws strategy is started with filters '
                  'that open the path to Cloudflare and let direct STUN '
                  'bypass the relay. If you already have a working zapret '
                  'strategy running, this step changes nothing.\n'
                  'However, you should add the necessary filters to your '
                  'strategy (if they are missing), otherwise workers and '
                  'calls may not work.\n'
                  'Exactly which filters to add to your strategy is '
                  'described in the README of this project.'),
    'boot.status_starting': ('Запуск winws…', 'Starting winws…'),
    'boot.status_ok': ('winws запущен', 'winws is running'),
    'boot.status_already': ('winws уже был запущен', 'winws was already running'),
    'boot.status_error': ('Не удалось запустить winws', 'winws failed to start'),
    'boot.status_stopped': ('winws остановлен', 'winws was stopped'),
    'boot.not_found': ('Файл zapret/winws-tg-calls-relay.bat не найден. '
                       'Без него звонки работать не будут — положите рядом '
                       'папки zapret/, lists/ и tg_calls/.',
                       'zapret/winws-tg-calls-relay.bat was not found. '
                       'Calls will not work without it - keep the zapret/, '
                       'lists/ and tg_calls/ folders next to the program.'),
    'boot.hint': ('Можно переходить к настройке прокси и релея.',
                  'You can proceed to configure the proxy and relay.'),
    'boot.output': ('Вывод winws', 'winws output'),

    'welcome.title': ('Добро пожаловать', 'Welcome'),
    'welcome.lead': ('Эта программа поднимает MTProto-прокси для Telegram и '
                     'TURN Relay для звонков, никакой ручной правки конфигов. '
                     'Все настройки сохраняются при перезапуске приложения.',
                     'This program raises an MTProto proxy for Telegram and a '
                     'TURN relay for calls, with no manual config editing. '
                     'All settings are saved when the app restarts.'),
    'welcome.f1_title': ('Прокси через CF Workers или CF Proxy '
                         '(проксирование через домен Cloudflare)',
                         'Proxy over CF Workers or CF Proxy '
                         '(proxying via Cloudflare domain)'),
    'welcome.f1_desc': ('WebSocket-мост к Telegram по трём воркерам: '
                        'ротация по DC, раздельные квоты аккаунтов и '
                        'авто-повтор при сбое. Так же доступно проксирование '
                        'через свой или общедоступные домены Cloudflare',
                        'A WebSocket bridge to Telegram over three workers: '
                        'per-DC rotation, separate account quotas, and '
                        'automatic retries on failure. Proxying through your '
                        'own or public Cloudflare domains is also available.'),
    'welcome.f2_title': ('Звонки через TURN Relay', 'Calls over a TURN relay'),
    'welcome.f2_desc': ('UDP трафик звонков перехватывается и идёт через '
                        'Cloudflare TURN по TLS (используется только в '
                        'групповых звонках или если в настройках аккаунта '
                        'выключен peer-to-peer). В результате звонки работают, '
                        'даже когда UDP Telegram недоступен по IP.',
                        'Call UDP traffic is intercepted and routed through '
                        'Cloudflare TURN over TLS (used only in group calls '
                        'or if peer-to-peer is disabled in account settings). '
                        'As a result, calls work even when Telegram UDP is '
                        'unavailable by IP.'),
    'welcome.f3_title': ('Совместим с zapret', 'Works with zapret'),
    'welcome.f3_desc': ('Релей живёт на своём приоритете WinDivert, '
                        'поэтому сосуществует с winws без каких либо проблем.',
                        'The relay runs at its own WinDivert priority, so it '
                        'coexists with winws without any problems.'),
    'welcome.note': ('Далее четыре коротких шага настройки.',
                     'Next, four short setup steps.'),

    'source.title': ('Метод маршрутизации', 'Routing Method'),
    'source.lead': ('Выберите способ маршрутизации трафика к серверам Telegram.',
                    'Choose the traffic routing method to Telegram servers.'),
    'source.workers_title': ('Свои воркеры CF', 'My own CF workers'),
    'source.workers_desc': ('Можно указать от 1 до 3 доменов воркеров. '
                            'Подходят, если они уже развёрнуты.',
                            'You can specify 1 to 3 worker domains. Suitable '
                            'if they are already deployed.'),
    'source.workers_link': ('Как настроить воркер', 'How to set up a worker'),
    'source.workers_hint': ('Заполните хотя бы одно поле.',
                            'Fill in at least one field.'),
    'source.domain_title': ('Свой домен для проксирования',
                            'My own proxy domain'),
    'source.domain_desc': ('Один домен за Cloudflare-прокси: трафик идёт на '
                           'kws<dc>.<домен>.',
                           'One domain behind a Cloudflare proxy: traffic '
                           'goes to kws<dc>.<domain>.'),
    'source.domain_link': ('Как настроить свой домен', 'How to set up your domain'),
    'source.public_link': ('Открыть список доменов', 'Open the domain list'),
    'source.public_title': ('Общедоступные домены', 'Public domains'),
    'source.public_desc': ('Готовый список из '
                           'Flowseal/tg-ws-proxy/cfproxy-domains.txt. '
                           'Самый простой вариант.',
                           'A ready-made list from '
                           'Flowseal/tg-ws-proxy/cfproxy-domains.txt. '
                           'The simplest option.'),
    'field.worker1': ('Воркер 1', 'Worker 1'),
    'field.worker2': ('Воркер 2', 'Worker 2'),
    'field.worker3': ('Воркер 3', 'Worker 3'),
    'field.domain': ('Домен', 'Domain'),

    'mtproto.title': ('Подключение MTProto', 'MTProto connection'),
    'mtproto.lead': ('Локальные параметры прокси: адрес и порт, на которых '
                     'он слушает, и секрет доступа.',
                     'Local proxy settings: the address and port it listens '
                     'on and the access secret.'),
    'field.host': ('IP-address', 'IP-address'),
    'field.port': ('Port', 'Port'),
    'field.secret': ('Secret', 'Secret'),
    'mtproto.secret_hint': ('dd-секрет: 32 hex-символа. Кнопка рядом '
                            'пересоздаёт его.',
                            'dd secret: 32 hex characters. The button next to '
                            'it regenerates it.'),
    'mtproto.link_preview': ('Ссылка для подключения', 'Connection link'),
    'mtproto.secret_bad': ('Секрет — ровно 32 hex-символа',
                           'The secret is exactly 32 hex characters'),
    'mtproto.host_bad': ('Введите корректный IPv4-адрес',
                         'Enter a valid IPv4 address'),
    'mtproto.port_bad': ('Порт от 1 до 65535', 'Port from 1 to 65535'),

    'err.domain': ('Введите корректный домен', 'Enter a valid domain'),
    'err.token': ('Введите токен', 'Enter the token'),
    'err.cf_key': ('Введите key id и API-токен', 'Enter the key id and the API token'),
    'err.creds': ('Заполните username и credential', 'Fill in username and credential'),
    'err.turn_url': ('URL вида turns://host:443', 'A URL like turns://host:443'),

    'run.title': ('Запуск прокси', 'Starting the proxy'),
    'run.starting': ('Запуск прокси…', 'Starting the proxy…'),
    'run.ok': ('Прокси запущен', 'The proxy is up'),
    'run.fail': ('Прокси не запустился', 'The proxy failed to start'),
    'run.connect_hint': ('После нажатия «Подключить» откроется Telegram Desktop с готовым прокси. '
                         'Если нет, то ссылку можно скопировать ниже.',
                         'After clicking "Connect", Telegram Desktop opens with a ready proxy. '
                         'If not, you can copy the link below.'),
    'run.err_hint': ('Проверьте, не занят ли порт и верны ли домены — '
                     'подробности в журнале ниже.',
                     'Check that the port is free and the domains are right - '
                     'details are in the log below.'),
    'run.waiting': ('Ждём, пока прокси начнёт слушать порт…',
                    'Waiting for the proxy to start listening…'),

    'turn.title': ('Настройка TURN Relay',
                   'TURN Relay setup'),
    'turn.lead': ('Укажите провайдера для генерации TURN-кредов (credentials).',
                  'Specify the provider for generating TURN credentials.'),
    'turn.hf_title': ('Свой токен Hugging Face', 'My own Hugging Face token'),
    'turn.hf_desc': ('10 ГБ/мес без банковской карты. Создайте аккаунт на '
                     'huggingface.co → Settings → Access tokens → New token '
                     '(роль read) и вставьте его сюда.',
                     '10 GB/month without a bank card. Create an account at '
                     'huggingface.co → Settings → Access tokens → New token '
                     '(role: read) and paste it here.'),
    'turn.cf_title': ('Аккаунт Cloudflare', 'Cloudflare account'),
    'turn.cf_desc': ('1000 ГБ/мес, нужна привязка банковской карты '
                     '(РФ не подходит). Dashboard → account → Realtime → '
                     'TURN keys → Create key (это key id); My Profile → API '
                     'Tokens → Create Token с правом Realtime : TURN : Edit '
                     '(это API-токен).',
                     '1000 GB/month, requires linking a bank card (not '
                     'available for RU). Dashboard → account → Realtime → '
                     'TURN keys → Create key (this is the key id); My '
                     'Profile → API Tokens → Create Token with Realtime : '
                     'TURN : Edit permission (this is the API token).'),
    'turn.custom_title': ('Другой TURN-сервер', 'Another TURN server'),
    'turn.custom_desc': ('Свой или чужой TURN: username, credential и адрес '
                         'turns://host:443. Креды проверяются пробным '
                         'проходом через сервер.',
                         'Your own or a third-party TURN: username, '
                         'credential and a turns://host:443 address. The '
                         'credentials are verified with a test round trip.'),
    'turn.public_title': ('Общий токен Hugging Face', 'Shared Hugging Face token'),
    'turn.public_desc': ('Общий токен Hugging Face, поэтому может быстро '
                         'закончиться лимит. Лучше создать свой.',
                         'Shared Hugging Face token, so the limit may run out '
                         'quickly. It is better to create your own.'),
    'field.hf_token': ('hf_token', 'hf_token'),
    'field.cf_key': ('TURN key id', 'TURN key id'),
    'field.cf_token': ('API токен', 'API token'),
    'field.turn_user': ('Username', 'Username'),
    'field.turn_cred': ('Credential', 'Credential'),
    'field.turn_url': ('TURN URL', 'TURN URL'),

    'check.title': ('Проверка настроек', 'Checking the settings'),
    'check.lead': ('Создание TURN-кредов и проверка, что путь звонка '
                   'доходит до сервера.',
                   'Creating TURN credentials and checking that the call '
                   'path reaches the server.'),
    'check.step_mint': ('Создание TURN-кредов', 'Creating TURN credentials'),
    'check.step_probe': ('Проверка TURN-пути', 'Checking the TURN path'),
    'check.step_relay': ('Запуск релея звонков', 'Starting the call relay'),
    'check.success': ('Успешно!', 'Success!'),
    'check.success_hint': ('Переход на главный экран.',
                     'Moving to the main screen.'),
    'check.fail': ('Проверка не пройдена', 'The check failed'),
    'check.working': ('Подождите несколько секунд…', 'Please wait a few seconds…'),
    'check.err_hint': ('Сервер TURN не ответил или отклонил креды — '
                       'проверьте токен/ключ и попробуйте ещё раз. '
                       'Подробности ниже.',
                       'The TURN server did not answer or rejected the '
                       'credentials - check the token/key and try again. '
                       'Details below.'),
    'turn.hf_link': ('Ссылка на huggingface.co/settings/tokens',
                     'Link to huggingface.co/settings/tokens'),
    'turn.cf_link': ('Документация Cloudflare', 'Cloudflare docs'),

    'set.title': ('Настройки', 'Settings'),
    'set.section_proxy': ('Настройка прокси MTProto', 'MTProto proxy settings'),
    'set.section_turn': ('Настройка TURN Relay для звонков Telegram',
                         'TURN relay settings for Telegram calls'),
    'set.lang': ('Язык интерфейса', 'Interface language'),
    'set.saved': ('Настройки сохранены', 'Settings saved'),
    'set.restarted': ('Службы перезапущены с новыми настройками',
                      'Services restarted with the new settings'),
    'set.turn_changed': ('TURN-креды обновлены', 'TURN credentials updated'),
    'set.section_proxy_hint': ('Режим подключения, адрес, порт и секрет.',
                               'Connection mode, address, port and secret.'),
    'set.tab_proxy': ('Прокси', 'Proxy'),
    'set.tab_calls': ('Звонки', 'Calls'),
    'set.tab_general': ('Общие', 'General'),
    'set.tab_locked': ('Сначала завершите настройку (мастер при первом запуске)',
                       'Complete the setup first (first-run wizard)'),
    'set.conn_title': ('Настройка MTProto-прокси', 'MTProto proxy settings'),
    'set.conn_hint': ('Адрес и порт, на которых слушает MTProto-прокси.',
                      'The address and port the MTProto proxy listens on.'),
    'set.lang_hint': ('Интерфейс переключится сразу, настройки сохранятся.',
                      'The interface switches right away, settings are kept.'),
    'set.about_title': ('О программе', 'About'),
    'set.about_text': ('Powered by Bogdan Logachev',
                       'Powered by Bogdan Logachev'),

    'tray.open': ('Открыть', 'Open'),
    'tray.exit': ('Выйти', 'Exit'),
    'tray.minimized': ('Свернуто в трей', 'Minimized to tray'),
    'set.startup_title': ('Запускать при включении ПК', 'Launch at Windows startup'),
    'set.startup_hint': ('Автоматически запускать приложение при старте системы.',
                          'Automatically launch the app on system startup.'),
    'set.startup_failed': ('Не удалось изменить настройки автозапуска',
                            'Failed to change startup settings'),

    'main.log': ('Журналы работы', 'Logs'),
    'main.title': ('Прокси и звонки', 'Proxy and calls'),
    'main.subtitle': ('MTProto-прокси и звонки через Cloudflare TURN',
                      'MTProto proxy and calls over Cloudflare TURN'),
    'main.status_running': ('Запущено', 'Running'),
    'main.status_partial': ('Работает частично', 'Partly working'),
    'main.status_stopped': ('Остановлено', 'Stopped'),
    'main.status_starting': ('Запуск…', 'Starting…'),
    'main.status_error': ('Ошибка запуска', 'Startup failed'),
    'main.status_setup': ('Нужна настройка', 'Setup required'),
    'main.hint_running': ('Прокси на {addr} и релей звонков активны.',
                          'The proxy on {addr} and the call relay are active.'),
    'main.hint_partial': ('Прокси работает, звонки — нет: проверьте TURN '
                          'в настройках.',
                          'The proxy works, calls do not: check TURN in the '
                          'settings.'),
    'main.hint_stopped': ('Нажмите «Запустить», чтобы поднять прокси и '
                          'релей.',
                          'Press Start to bring the proxy and the relay up.'),
    'main.hint_starting': ('Поднимаем службы — это займёт пару секунд.',
                           'Starting the services - this takes a moment.'),
    'main.hint_error': ('Подробности — в журнале ниже.',
                        'The details are in the log below.'),
    'main.hint_setup': ('Откройте настройки и заполните недостающие поля.',
                        'Open the settings and fill in the missing fields.'),
    'main.tab_proxy': ('Прокси', 'Proxy'),
    'main.tab_relay': ('Релей', 'Relay'),
    'main.tab_winws': ('winws', 'winws'),
    'main.need_setup': ('Настройка не завершена — откройте параметры.',
                        'Setup is unfinished - open the settings.'),
    'main.no_admin': ('Нет прав администратора: звонки работать не будут. '
                      'Перезапустите от имени администратора.',
                      'No administrator rights: calls will not work. Restart '
                      'as administrator.'),
}


def set_lang(lang: str) -> None:
    global _lang, _idx
    if lang not in LANGS:
        lang = 'ru'
    _lang = lang
    _idx = LANGS.index(lang)


def get_lang() -> str:
    return _lang


def t(key: str, **kwargs) -> str:
    entry = STRINGS.get(key)
    if entry is None:
        return key
    text = entry[_idx]
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text