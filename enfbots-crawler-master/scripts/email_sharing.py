import pandas as pd
import logging
import tldextract
from pylcs import lcs_sequence_length
from email.utils import getaddresses
from collections import namedtuple

from sqlalchemy import create_engine, text

from enfbots_crawler import Config

DomainsAndFullAddr = namedtuple('DomainsAndFullAddr', ['domains', 'all_senders'])
RecDict = dict[str, DomainsAndFullAddr[set[str], set[str]]]


logger = logging.getLogger("enfbots_crawler")


def parse_addr_header(header: str, sybil: bool = False) -> tuple[str, str]:
    if not header:
        return '', ''
    addr, name = '', ''
    parsed_addresses = getaddresses([header])
    if len(parsed_addresses) == 0:
        logging.error(f'No address in : {header}')
        raise Exception(f'No address in : {header}')
    elif len(parsed_addresses) == 1:
        [(name, addr)] = parsed_addresses
    else:
        logging.warning(f'Parsed multiple addresses: {parsed_addresses}')
        for tuple_addr in parsed_addresses:
            name = tuple_addr[0]
            addr = tuple_addr[1]

            if sybil:
                substring = '@sybilmail'
            else:
                substring = '@'
            if substring in addr:
                logging.warning(f'Using: {addr}')
                break
    return addr, name


def parse_to(to_header: str) -> str:
    return parse_addr_header(to_header, sybil=True)[0]


def parse_from(from_header: str) -> str:
    return parse_addr_header(from_header, sybil=False)[0]


def parse_url(mail: str) -> str:
    return tldextract.extract(mail).domain


def load_csv(path: str) -> pd.DataFrame:
    mails = pd.read_csv(path, index_col=0)

    mails.rename(columns={'mailbox_id': 'id', 'id': 'intid', 'to': 'to',
                          'from_': 'from', 'subject': 'subject', 'timestamp': 'date'})

    mails['parsed_to'] = mails['to'].map(parse_to)
    mails['parsed_from'] = mails['from'].map(parse_from)
    mails['domain_from'] = mails['parsed_from'].map(parse_url)
    return mails


def load_db() -> pd.DataFrame:
    engine = create_engine(Config().get_db_url(), echo=False, future=False)
    email_df = pd.read_sql(
        text("""
            SELECT j.id, j.domain,
            w.id AS wid, w.reg_status, w.email_verification_status, w.lang as wlang,
            m.id AS intid, m.from_header AS from, m.to_header AS to, m.subject_header AS subject, m.date_header AS date,
            m.headers_raw, m.language AS mlang, m.is_verify_mail_regex, m.classification_regex, 
            m.has_link, m.clicked_link, m.activation_link, m.has_code, m.verification_code,
            m.successful_verification, m.notes as id
            FROM public.jobs j
            INNER JOIN public.websites w ON w.job_id = j.id
            INNER JOIN public.mails m ON m.website_id = w.id
            WHERE j.crawl_id = 'tranco-ux-202206' OR j.crawl_id = 'tranco-noux-202206'"""),
        con=engine,
        parse_dates=[
            'date',
        ]
    )

    email_df['parsed_to'] = email_df['to'].map(parse_to)
    email_df['parsed_from'] = email_df['from'].map(parse_from)
    email_df['domain_from'] = email_df['parsed_from'].map(parse_url)
    return email_df


def check_sharing(df: pd.DataFrame) -> RecDict:
    multiple_receivers = dict()
    for group_name, df_group in df.groupby(['parsed_to']):
        from_domains = set(d.lower() if not pd.isna(d) else '' for d in df_group['domain_from'])
        from_full = set(d.lower() if not pd.isna(d) else '' for d in df_group['from'])
        multiple_receivers[group_name] = DomainsAndFullAddr(from_domains, from_full)

    return multiple_receivers


def get_counts(multiple_receivers: RecDict) -> None:
    counts = {i: 0 for i in range(1000)}
    for receiver in multiple_receivers:
        counts[len(multiple_receivers[receiver].domains)] += 1
    print(counts)


def get_score(s1: str, s2: str) -> float:
    strlen = max((len(s1) + len(s2))/2, 1)
    lcs = lcs_sequence_length(s1, s2)
    score = lcs**2 / strlen**2

    return score


def get_all_scores(strs: list[str]) -> list[float]:
    scores = []
    for i in range(len(strs)):
        for j in range(i+1, len(strs)):
            scores.append(get_score(strs[i], strs[j]))
    return scores


def get_common_sender(multiple_receivers: RecDict) -> str:
    rec_list = ('gmail', 'zoom', 'mailchimpapp', 'wordpress', 'posteo')
    for receiver in multiple_receivers:
        if receiver in rec_list:
            return receiver
    return ''


def print_scores_sorted(multiple_receivers: RecDict):
    m2 = dict()
    for receiver in multiple_receivers:
        if len(multiple_receivers[receiver].domains) == 2:
            m2[receiver] = multiple_receivers[receiver].domains
    for receiver in sorted(m2, key=lambda y: get_score(*m2[y])):
        print(f'{m2[receiver]} score {get_score(*m2[receiver])}')


def report_multiple_senders_csv(df: pd.DataFrame, multiple_receivers: RecDict) -> None:
    # Result table:
    # * receiver
    # * list of domains senders
    # * score
    # * whether is a common mail sender
    # * ids of emails
    # * subjects of emails
    res = []
    for receiver in multiple_receivers:
        row = dict()
        row['receiver'] = receiver.lower()
        row['domains'] = multiple_receivers[receiver].domains
        row['all_senders'] = multiple_receivers[receiver].all_senders
        if len(row['domains']) == 1 or not receiver or receiver in ('HCP-Users@humanconnectome.org',
                                                                    'hcp-users@humanconnectome.org', 'nan'):
            continue  # no sharing -> ignore
        row['score'] = get_all_scores(list(row['domains']))
        row['common_sender'] = get_common_sender(multiple_receivers)
        df_corr = df[df['parsed_to'] == receiver]
        row['all_mail_ids'] = list(df_corr.intid)
        row['all_mail_subjects'] = list(df_corr.subject)
        res.append(row)
    pd_out = pd.DataFrame(res)

    if GET_REG_DOM:
        reg_df = pd.read_csv('/home/kubicekk/Documents/research/enf-bots/usenix_www/tables/all/website.csv',
                             index_col=0)
        pd_out['wid'] = pd_out['receiver'].apply(lambda email: get_reg_website(reg_df, email, 'wid'))
        pd_out['crawl_domain'] = pd_out['wid'].apply(lambda wid: get_reg_data(reg_df, wid, 'domain'))
        pd_out['tranco_index'] = pd_out['wid'].apply(lambda wid: get_reg_data(reg_df, wid, 'tranco_index'))
        pd_out['chrome_ux_url'] = pd_out['wid'].apply(lambda wid: get_reg_data(reg_df, wid, 'chrome_ux_url'))
        pd_out['reg_url'] = pd_out['wid'].apply(lambda wid: get_reg_data(reg_df, wid, 'reg_url'))
        pd_out['newsletter_url'] = pd_out['wid'].apply(lambda wid: get_reg_data(reg_df, wid, 'newsletter_url'))
        pd_out['pp_url'] = pd_out['wid'].apply(lambda wid: get_reg_data(reg_df, wid, 'pp_url'))
        pd_out['tc_url'] = pd_out['wid'].apply(lambda wid: get_reg_data(reg_df, wid, 'tc_url'))
        pd_out['lang'] = pd_out['wid'].apply(lambda wid: get_reg_data(reg_df, wid, 'lang'))
        pd_out['reg_status'] = pd_out['wid'].apply(lambda wid: get_reg_data(reg_df, wid, 'reg_status'))
        pd_out['email_verification_status'] = pd_out['wid'].apply(lambda wid: get_reg_data(reg_df, wid,
                                                                                           'email_verification_status'))
        pd_out['states'] = pd_out['wid'].apply(lambda wid: get_reg_data(reg_df, wid, 'states'))

    pd_out.to_csv('/tmp/email_sharing.csv')


def get_reg_website(df: pd.DataFrame, mail: str, entry: str) -> int | None:
    values = df[df['email'] == mail][entry].values
    return values[0] if values.size > 0 else None


def get_reg_data(df: pd.DataFrame, wid: int | None, entry: str) -> str:
    if pd.isna(wid):
        return ''
    values = df[df['wid'] == wid][entry].values
    return values[0] if values.size > 0 else ''


def process():
    if LOAD_ONLINE:
        mails = load_db()
    else:
        mails = load_csv('~/Documents/research/enf-bots/usenix_www/tables/mails_sybil/processed_mails.csv')
    multiple_receivers = check_sharing(mails)
    get_counts(multiple_receivers)
    print_scores_sorted(multiple_receivers)
    report_multiple_senders_csv(mails, multiple_receivers)


if __name__ == '__main__':
    GET_REG_DOM = True
    LOAD_ONLINE = True
    process()
