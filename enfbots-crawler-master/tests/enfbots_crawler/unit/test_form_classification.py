import bs4
from pathlib import Path

from enfbots_crawler.languages import Language

from enfbots_crawler import FormType
from enfbots_crawler.form_bs import FormBS

form_html = """
<form id="register" method="post" action="./ucp.php?mode=register">

<div class="panel">
<div class="inner">

<fieldset class="fields2">
<dl><dd><strong>Please note that you will need to enter a valid email address before your account is activated. You will receive an email at the address you provide that contains an account activation link.</strong></dd></dl>
<dl>
<dt><label for="username">Username:</label><br><span>Username must be between 3 characters and 20 characters long and use only ASCII characters, so no special symbols.</span></dt>
<dd><input type="text" tabindex="1" name="username" id="username" size="25" value="" class="inputbox autowidth" title="Username"></dd>
</dl>
<dl>
<dt><label for="email">Email address:</label></dt>
<dd><input type="email" tabindex="2" name="email" id="email" size="25" maxlength="100" value="" class="inputbox autowidth" title="Email address" autocomplete="off"></dd>
</dl>
<dl>
<dt><label for="new_password">Password:</label><br><span>Must be at least 8 characters long.</span></dt>
<dd><input type="password" tabindex="4" name="new_password" id="new_password" size="25" value="" class="inputbox autowidth" title="New password" autocomplete="off"></dd>
</dl>
<dl>
<dt><label for="password_confirm">Confirm password:</label></dt>
<dd><input type="password" tabindex="5" name="password_confirm" id="password_confirm" size="25" value="" class="inputbox autowidth" title="Confirm password" autocomplete="off"></dd>
</dl>


<dl>
<dt><label for="lang">Language:</label></dt>
<dd><select name="lang" id="lang" onchange="change_language(this.value); return false;" tabindex="6" title="Language"><option value="en" selected="selected">British English</option></select></dd>
</dl>

<dl>
<dt><label for="timezone">My timezone:</label></dt>
<dd id="tz_select_date" style="display: none;">
<select name="tz_date" id="tz_date" class="autowidth tz_select">
<option value="">Select current time</option>
<option value="UTC-11:00 - Pacific/Midway - 27 Nov 2021, 04:20">UTC-11:00 - 27 Nov 2021, 04:20</option>
<option value="UTC-10:00 - America/Adak - 27 Nov 2021, 05:20">UTC-10:00 - 27 Nov 2021, 05:20</option>
<option value="UTC-09:30 - Pacific/Marquesas - 27 Nov 2021, 05:50">UTC-09:30 - 27 Nov 2021, 05:50</option>
<option value="UTC-09:00 - America/Anchorage - 27 Nov 2021, 06:20">UTC-09:00 - 27 Nov 2021, 06:20</option>
<option value="UTC-08:00 - America/Los_Angeles - 27 Nov 2021, 07:20">UTC-08:00 - 27 Nov 2021, 07:20</option>
<option value="UTC-07:00 - America/Boise - 27 Nov 2021, 08:20">UTC-07:00 - 27 Nov 2021, 08:20</option>
<option value="UTC-06:00 - America/Bahia_Banderas - 27 Nov 2021, 09:20">UTC-06:00 - 27 Nov 2021, 09:20</option>
<option value="UTC-05:00 - America/Atikokan - 27 Nov 2021, 10:20">UTC-05:00 - 27 Nov 2021, 10:20</option>
<option value="UTC-04:00 - America/Anguilla - 27 Nov 2021, 11:20">UTC-04:00 - 27 Nov 2021, 11:20</option>
<option value="UTC-03:30 - America/St_Johns - 27 Nov 2021, 11:50">UTC-03:30 - 27 Nov 2021, 11:50</option>
<option value="UTC-03:00 - America/Araguaina - 27 Nov 2021, 12:20">UTC-03:00 - 27 Nov 2021, 12:20</option>
<option value="UTC-02:00 - America/Noronha - 27 Nov 2021, 13:20">UTC-02:00 - 27 Nov 2021, 13:20</option>
<option value="UTC-01:00 - America/Scoresbysund - 27 Nov 2021, 14:20">UTC-01:00 - 27 Nov 2021, 14:20</option>
<option value="UTC+00:00 - UTC - 27 Nov 2021, 15:20" selected="selected">UTC+00:00 - 27 Nov 2021, 15:20</option>
<option value="UTC+01:00 - Africa/Algiers - 27 Nov 2021, 16:20">UTC+01:00 - 27 Nov 2021, 16:20</option>
<option value="UTC+02:00 - Africa/Blantyre - 27 Nov 2021, 17:20">UTC+02:00 - 27 Nov 2021, 17:20</option>
<option value="UTC+03:00 - Africa/Addis_Ababa - 27 Nov 2021, 18:20">UTC+03:00 - 27 Nov 2021, 18:20</option>
<option value="UTC+03:30 - Asia/Tehran - 27 Nov 2021, 18:50">UTC+03:30 - 27 Nov 2021, 18:50</option>
<option value="UTC+04:00 - Asia/Baku - 27 Nov 2021, 19:20">UTC+04:00 - 27 Nov 2021, 19:20</option>
<option value="UTC+04:30 - Asia/Kabul - 27 Nov 2021, 19:50">UTC+04:30 - 27 Nov 2021, 19:50</option>
<option value="UTC+05:00 - Antarctica/Mawson - 27 Nov 2021, 20:20">UTC+05:00 - 27 Nov 2021, 20:20</option>
<option value="UTC+05:30 - Asia/Colombo - 27 Nov 2021, 20:50">UTC+05:30 - 27 Nov 2021, 20:50</option>
<option value="UTC+05:45 - Asia/Kathmandu - 27 Nov 2021, 21:05">UTC+05:45 - 27 Nov 2021, 21:05</option>
<option value="UTC+06:00 - Antarctica/Vostok - 27 Nov 2021, 21:20">UTC+06:00 - 27 Nov 2021, 21:20</option>
<option value="UTC+06:30 - Asia/Yangon - 27 Nov 2021, 21:50">UTC+06:30 - 27 Nov 2021, 21:50</option>
<option value="UTC+07:00 - Antarctica/Davis - 27 Nov 2021, 22:20">UTC+07:00 - 27 Nov 2021, 22:20</option>
<option value="UTC+08:00 - Asia/Brunei - 27 Nov 2021, 23:20">UTC+08:00 - 27 Nov 2021, 23:20</option>
<option value="UTC+08:45 - Australia/Eucla - 28 Nov 2021, 00:05">UTC+08:45 - 28 Nov 2021, 00:05</option>
<option value="UTC+09:00 - Asia/Chita - 28 Nov 2021, 00:20">UTC+09:00 - 28 Nov 2021, 00:20</option>
<option value="UTC+09:30 - Australia/Darwin - 28 Nov 2021, 00:50">UTC+09:30 - 28 Nov 2021, 00:50</option>
<option value="UTC+10:00 - Antarctica/DumontDUrville - 28 Nov 2021, 01:20">UTC+10:00 - 28 Nov 2021, 01:20</option>
<option value="UTC+10:30 - Australia/Adelaide - 28 Nov 2021, 01:50">UTC+10:30 - 28 Nov 2021, 01:50</option>
<option value="UTC+11:00 - Antarctica/Casey - 28 Nov 2021, 02:20">UTC+11:00 - 28 Nov 2021, 02:20</option>
<option value="UTC+12:00 - Asia/Anadyr - 28 Nov 2021, 03:20">UTC+12:00 - 28 Nov 2021, 03:20</option>
<option value="UTC+13:00 - Antarctica/McMurdo - 28 Nov 2021, 04:20">UTC+13:00 - 28 Nov 2021, 04:20</option>
<option value="UTC+13:45 - Pacific/Chatham - 28 Nov 2021, 05:05">UTC+13:45 - 28 Nov 2021, 05:05</option>
<option value="UTC+14:00 - Pacific/Kiritimati - 28 Nov 2021, 05:20">UTC+14:00 - 28 Nov 2021, 05:20</option>
</select>
<input type="button" id="tz_select_date_suggest" class="button2" style="display: none;" timezone-preselect="true" data-l-suggestion="Suggestion: %s" value="Suggestion: %s">
</dd>
<dd>
<select name="tz" id="timezone" class="autowidth tz_select">
<option value="">Select timezone</option>
<optgroup label="UTC-11:00 - 27 Nov 2021, 04:20" data-tz-value="UTC-11:00 - Pacific/Midway - 27 Nov 2021, 04:20">
<option title="UTC-11:00 - Pacific/Midway" value="Pacific/Midway">Pacific/Midway</option>
<option title="UTC-11:00 - Pacific/Niue" value="Pacific/Niue">Pacific/Niue</option>
<option title="UTC-11:00 - Pacific/Pago Pago" value="Pacific/Pago_Pago">Pacific/Pago Pago</option>
</optgroup>
<optgroup label="UTC-10:00 - 27 Nov 2021, 05:20" data-tz-value="UTC-10:00 - America/Adak - 27 Nov 2021, 05:20">
<option title="UTC-10:00 - America/Adak" value="America/Adak">America/Adak</option>
<option title="UTC-10:00 - Pacific/Honolulu" value="Pacific/Honolulu">Pacific/Honolulu</option>
<option title="UTC-10:00 - Pacific/Rarotonga" value="Pacific/Rarotonga">Pacific/Rarotonga</option>
<option title="UTC-10:00 - Pacific/Tahiti" value="Pacific/Tahiti">Pacific/Tahiti</option>
</optgroup>
<optgroup label="UTC-09:30 - 27 Nov 2021, 05:50" data-tz-value="UTC-09:30 - Pacific/Marquesas - 27 Nov 2021, 05:50">
<option title="UTC-09:30 - Pacific/Marquesas" value="Pacific/Marquesas">Pacific/Marquesas</option>
</optgroup>
<optgroup label="UTC-09:00 - 27 Nov 2021, 06:20" data-tz-value="UTC-09:00 - America/Anchorage - 27 Nov 2021, 06:20">
<option title="UTC-09:00 - America/Anchorage" value="America/Anchorage">America/Anchorage</option>
<option title="UTC-09:00 - America/Juneau" value="America/Juneau">America/Juneau</option>
<option title="UTC-09:00 - America/Metlakatla" value="America/Metlakatla">America/Metlakatla</option>
<option title="UTC-09:00 - America/Nome" value="America/Nome">America/Nome</option>
<option title="UTC-09:00 - America/Sitka" value="America/Sitka">America/Sitka</option>
<option title="UTC-09:00 - America/Yakutat" value="America/Yakutat">America/Yakutat</option>
<option title="UTC-09:00 - Pacific/Gambier" value="Pacific/Gambier">Pacific/Gambier</option>
</optgroup>
<optgroup label="UTC-08:00 - 27 Nov 2021, 07:20" data-tz-value="UTC-08:00 - America/Los_Angeles - 27 Nov 2021, 07:20">
<option title="UTC-08:00 - America/Los Angeles" value="America/Los_Angeles">America/Los Angeles</option>
<option title="UTC-08:00 - America/Tijuana" value="America/Tijuana">America/Tijuana</option>
<option title="UTC-08:00 - America/Vancouver" value="America/Vancouver">America/Vancouver</option>
<option title="UTC-08:00 - Pacific/Pitcairn" value="Pacific/Pitcairn">Pacific/Pitcairn</option>
</optgroup>
<optgroup label="UTC-07:00 - 27 Nov 2021, 08:20" data-tz-value="UTC-07:00 - America/Boise - 27 Nov 2021, 08:20">
<option title="UTC-07:00 - America/Boise" value="America/Boise">America/Boise</option>
<option title="UTC-07:00 - America/Cambridge Bay" value="America/Cambridge_Bay">America/Cambridge Bay</option>
<option title="UTC-07:00 - America/Chihuahua" value="America/Chihuahua">America/Chihuahua</option>
<option title="UTC-07:00 - America/Creston" value="America/Creston">America/Creston</option>
<option title="UTC-07:00 - America/Dawson" value="America/Dawson">America/Dawson</option>
<option title="UTC-07:00 - America/Dawson Creek" value="America/Dawson_Creek">America/Dawson Creek</option>
<option title="UTC-07:00 - America/Denver" value="America/Denver">America/Denver</option>
<option title="UTC-07:00 - America/Edmonton" value="America/Edmonton">America/Edmonton</option>
<option title="UTC-07:00 - America/Fort_Nelson" value="America/Fort_Nelson">America/Fort_Nelson</option>
<option title="UTC-07:00 - America/Hermosillo" value="America/Hermosillo">America/Hermosillo</option>
<option title="UTC-07:00 - America/Inuvik" value="America/Inuvik">America/Inuvik</option>
<option title="UTC-07:00 - America/Mazatlan" value="America/Mazatlan">America/Mazatlan</option>
<option title="UTC-07:00 - America/Ojinaga" value="America/Ojinaga">America/Ojinaga</option>
<option title="UTC-07:00 - America/Phoenix" value="America/Phoenix">America/Phoenix</option>
<option title="UTC-07:00 - America/Whitehorse" value="America/Whitehorse">America/Whitehorse</option>
<option title="UTC-07:00 - America/Yellowknife" value="America/Yellowknife">America/Yellowknife</option>
</optgroup>
<optgroup label="UTC-06:00 - 27 Nov 2021, 09:20" data-tz-value="UTC-06:00 - America/Bahia_Banderas - 27 Nov 2021, 09:20">
<option title="UTC-06:00 - America/Bahia Banderas" value="America/Bahia_Banderas">America/Bahia Banderas</option>
<option title="UTC-06:00 - America/Belize" value="America/Belize">America/Belize</option>
<option title="UTC-06:00 - America/Chicago" value="America/Chicago">America/Chicago</option>
<option title="UTC-06:00 - America/Costa Rica" value="America/Costa_Rica">America/Costa Rica</option>
<option title="UTC-06:00 - America/El Salvador" value="America/El_Salvador">America/El Salvador</option>
<option title="UTC-06:00 - America/Guatemala" value="America/Guatemala">America/Guatemala</option>
<option title="UTC-06:00 - America/Indiana/Knox" value="America/Indiana/Knox">America/Indiana/Knox</option>
<option title="UTC-06:00 - America/Indiana/Tell City" value="America/Indiana/Tell_City">America/Indiana/Tell City</option>
<option title="UTC-06:00 - America/Managua" value="America/Managua">America/Managua</option>
<option title="UTC-06:00 - America/Matamoros" value="America/Matamoros">America/Matamoros</option>
<option title="UTC-06:00 - America/Menominee" value="America/Menominee">America/Menominee</option>
<option title="UTC-06:00 - America/Merida" value="America/Merida">America/Merida</option>
<option title="UTC-06:00 - America/Mexico City" value="America/Mexico_City">America/Mexico City</option>
<option title="UTC-06:00 - America/Monterrey" value="America/Monterrey">America/Monterrey</option>
<option title="UTC-06:00 - America/North Dakota/Beulah" value="America/North_Dakota/Beulah">America/North Dakota/Beulah</option>
<option title="UTC-06:00 - America/North Dakota/Center" value="America/North_Dakota/Center">America/North Dakota/Center</option>
<option title="UTC-06:00 - America/North Dakota/New Salem" value="America/North_Dakota/New_Salem">America/North Dakota/New Salem</option>
<option title="UTC-06:00 - America/Rainy River" value="America/Rainy_River">America/Rainy River</option>
<option title="UTC-06:00 - America/Rankin Inlet" value="America/Rankin_Inlet">America/Rankin Inlet</option>
<option title="UTC-06:00 - America/Regina" value="America/Regina">America/Regina</option>
<option title="UTC-06:00 - America/Resolute" value="America/Resolute">America/Resolute</option>
<option title="UTC-06:00 - America/Swift Current" value="America/Swift_Current">America/Swift Current</option>
<option title="UTC-06:00 - America/Tegucigalpa" value="America/Tegucigalpa">America/Tegucigalpa</option>
<option title="UTC-06:00 - America/Winnipeg" value="America/Winnipeg">America/Winnipeg</option>
<option title="UTC-06:00 - Pacific/Galapagos" value="Pacific/Galapagos">Pacific/Galapagos</option>
</optgroup>
<optgroup label="UTC-05:00 - 27 Nov 2021, 10:20" data-tz-value="UTC-05:00 - America/Atikokan - 27 Nov 2021, 10:20">
<option title="UTC-05:00 - America/Atikokan" value="America/Atikokan">America/Atikokan</option>
<option title="UTC-05:00 - America/Bogota" value="America/Bogota">America/Bogota</option>
<option title="UTC-05:00 - America/Cancun" value="America/Cancun">America/Cancun</option>
<option title="UTC-05:00 - America/Cayman" value="America/Cayman">America/Cayman</option>
<option title="UTC-05:00 - America/Detroit" value="America/Detroit">America/Detroit</option>
<option title="UTC-05:00 - America/Eirunepe" value="America/Eirunepe">America/Eirunepe</option>
<option title="UTC-05:00 - America/Grand Turk" value="America/Grand_Turk">America/Grand Turk</option>
<option title="UTC-05:00 - America/Guayaquil" value="America/Guayaquil">America/Guayaquil</option>
<option title="UTC-05:00 - America/Havana" value="America/Havana">America/Havana</option>
<option title="UTC-05:00 - America/Indiana/Indianapolis" value="America/Indiana/Indianapolis">America/Indiana/Indianapolis</option>
<option title="UTC-05:00 - America/Indiana/Marengo" value="America/Indiana/Marengo">America/Indiana/Marengo</option>
<option title="UTC-05:00 - America/Indiana/Petersburg" value="America/Indiana/Petersburg">America/Indiana/Petersburg</option>
<option title="UTC-05:00 - America/Indiana/Vevay" value="America/Indiana/Vevay">America/Indiana/Vevay</option>
<option title="UTC-05:00 - America/Indiana/Vincennes" value="America/Indiana/Vincennes">America/Indiana/Vincennes</option>
<option title="UTC-05:00 - America/Indiana/Winamac" value="America/Indiana/Winamac">America/Indiana/Winamac</option>
<option title="UTC-05:00 - America/Iqaluit" value="America/Iqaluit">America/Iqaluit</option>
<option title="UTC-05:00 - America/Jamaica" value="America/Jamaica">America/Jamaica</option>
<option title="UTC-05:00 - America/Kentucky/Louisville" value="America/Kentucky/Louisville">America/Kentucky/Louisville</option>
<option title="UTC-05:00 - America/Kentucky/Monticello" value="America/Kentucky/Monticello">America/Kentucky/Monticello</option>
<option title="UTC-05:00 - America/Lima" value="America/Lima">America/Lima</option>
<option title="UTC-05:00 - America/Nassau" value="America/Nassau">America/Nassau</option>
<option title="UTC-05:00 - America/New York" value="America/New_York">America/New York</option>
<option title="UTC-05:00 - America/Nipigon" value="America/Nipigon">America/Nipigon</option>
<option title="UTC-05:00 - America/Panama" value="America/Panama">America/Panama</option>
<option title="UTC-05:00 - America/Pangnirtung" value="America/Pangnirtung">America/Pangnirtung</option>
<option title="UTC-05:00 - America/Port-au-Prince" value="America/Port-au-Prince">America/Port-au-Prince</option>
<option title="UTC-05:00 - America/Rio Branco" value="America/Rio_Branco">America/Rio Branco</option>
<option title="UTC-05:00 - America/Thunder Bay" value="America/Thunder_Bay">America/Thunder Bay</option>
<option title="UTC-05:00 - America/Toronto" value="America/Toronto">America/Toronto</option>
<option title="UTC-05:00 - Pacific/Easter" value="Pacific/Easter">Pacific/Easter</option>
</optgroup>
<optgroup label="UTC-04:00 - 27 Nov 2021, 11:20" data-tz-value="UTC-04:00 - America/Anguilla - 27 Nov 2021, 11:20">
<option title="UTC-04:00 - America/Anguilla" value="America/Anguilla">America/Anguilla</option>
<option title="UTC-04:00 - America/Antigua" value="America/Antigua">America/Antigua</option>
<option title="UTC-04:00 - America/Aruba" value="America/Aruba">America/Aruba</option>
<option title="UTC-04:00 - America/Barbados" value="America/Barbados">America/Barbados</option>
<option title="UTC-04:00 - America/Blanc-Sablon" value="America/Blanc-Sablon">America/Blanc-Sablon</option>
<option title="UTC-04:00 - America/Boa Vista" value="America/Boa_Vista">America/Boa Vista</option>
<option title="UTC-04:00 - America/Campo Grande" value="America/Campo_Grande">America/Campo Grande</option>
<option title="UTC-04:00 - America/Caracas" value="America/Caracas">America/Caracas</option>
<option title="UTC-04:00 - America/Cuiaba" value="America/Cuiaba">America/Cuiaba</option>
<option title="UTC-04:00 - America/Curacao" value="America/Curacao">America/Curacao</option>
<option title="UTC-04:00 - America/Dominica" value="America/Dominica">America/Dominica</option>
<option title="UTC-04:00 - America/Glace Bay" value="America/Glace_Bay">America/Glace Bay</option>
<option title="UTC-04:00 - America/Goose Bay" value="America/Goose_Bay">America/Goose Bay</option>
<option title="UTC-04:00 - America/Grenada" value="America/Grenada">America/Grenada</option>
<option title="UTC-04:00 - America/Guadeloupe" value="America/Guadeloupe">America/Guadeloupe</option>
<option title="UTC-04:00 - America/Guyana" value="America/Guyana">America/Guyana</option>
<option title="UTC-04:00 - America/Halifax" value="America/Halifax">America/Halifax</option>
<option title="UTC-04:00 - America/Kralendijk" value="America/Kralendijk">America/Kralendijk</option>
<option title="UTC-04:00 - America/La Paz" value="America/La_Paz">America/La Paz</option>
<option title="UTC-04:00 - America/Lower Princes" value="America/Lower_Princes">America/Lower Princes</option>
<option title="UTC-04:00 - America/Manaus" value="America/Manaus">America/Manaus</option>
<option title="UTC-04:00 - America/Marigot" value="America/Marigot">America/Marigot</option>
<option title="UTC-04:00 - America/Martinique" value="America/Martinique">America/Martinique</option>
<option title="UTC-04:00 - America/Moncton" value="America/Moncton">America/Moncton</option>
<option title="UTC-04:00 - America/Montserrat" value="America/Montserrat">America/Montserrat</option>
<option title="UTC-04:00 - America/Port of Spain" value="America/Port_of_Spain">America/Port of Spain</option>
<option title="UTC-04:00 - America/Porto Velho" value="America/Porto_Velho">America/Porto Velho</option>
<option title="UTC-04:00 - America/Puerto Rico" value="America/Puerto_Rico">America/Puerto Rico</option>
<option title="UTC-04:00 - America/Santo Domingo" value="America/Santo_Domingo">America/Santo Domingo</option>
<option title="UTC-04:00 - America/St. Barthelemy" value="America/St_Barthelemy">America/St. Barthelemy</option>
<option title="UTC-04:00 - America/St. Kitts" value="America/St_Kitts">America/St. Kitts</option>
<option title="UTC-04:00 - America/St. Lucia" value="America/St_Lucia">America/St. Lucia</option>
<option title="UTC-04:00 - America/St. Thomas" value="America/St_Thomas">America/St. Thomas</option>
<option title="UTC-04:00 - America/St. Vincent" value="America/St_Vincent">America/St. Vincent</option>
<option title="UTC-04:00 - America/Thule" value="America/Thule">America/Thule</option>
<option title="UTC-04:00 - America/Tortola" value="America/Tortola">America/Tortola</option>
<option title="UTC-04:00 - Atlantic/Bermuda" value="Atlantic/Bermuda">Atlantic/Bermuda</option>
</optgroup>
<optgroup label="UTC-03:30 - 27 Nov 2021, 11:50" data-tz-value="UTC-03:30 - America/St_Johns - 27 Nov 2021, 11:50">
<option title="UTC-03:30 - America/St. Johns" value="America/St_Johns">America/St. Johns</option>
</optgroup>
<optgroup label="UTC-03:00 - 27 Nov 2021, 12:20" data-tz-value="UTC-03:00 - America/Araguaina - 27 Nov 2021, 12:20">
<option title="UTC-03:00 - America/Araguaina" value="America/Araguaina">America/Araguaina</option>
<option title="UTC-03:00 - America/Argentina/Buenos Aires" value="America/Argentina/Buenos_Aires">America/Argentina/Buenos Aires</option>
<option title="UTC-03:00 - America/Argentina/Catamarca" value="America/Argentina/Catamarca">America/Argentina/Catamarca</option>
<option title="UTC-03:00 - America/Argentina/Cordoba" value="America/Argentina/Cordoba">America/Argentina/Cordoba</option>
<option title="UTC-03:00 - America/Argentina/Jujuy" value="America/Argentina/Jujuy">America/Argentina/Jujuy</option>
<option title="UTC-03:00 - America/Argentina/La Rioja" value="America/Argentina/La_Rioja">America/Argentina/La Rioja</option>
<option title="UTC-03:00 - America/Argentina/Mendoza" value="America/Argentina/Mendoza">America/Argentina/Mendoza</option>
<option title="UTC-03:00 - America/Argentina/Rio Gallegos" value="America/Argentina/Rio_Gallegos">America/Argentina/Rio Gallegos</option>
<option title="UTC-03:00 - America/Argentina/Salta" value="America/Argentina/Salta">America/Argentina/Salta</option>
<option title="UTC-03:00 - America/Argentina/San Juan" value="America/Argentina/San_Juan">America/Argentina/San Juan</option>
<option title="UTC-03:00 - America/Argentina/San Luis" value="America/Argentina/San_Luis">America/Argentina/San Luis</option>
<option title="UTC-03:00 - America/Argentina/Tucuman" value="America/Argentina/Tucuman">America/Argentina/Tucuman</option>
<option title="UTC-03:00 - America/Argentina/Ushuaia" value="America/Argentina/Ushuaia">America/Argentina/Ushuaia</option>
<option title="UTC-03:00 - America/Asuncion" value="America/Asuncion">America/Asuncion</option>
<option title="UTC-03:00 - America/Bahia" value="America/Bahia">America/Bahia</option>
<option title="UTC-03:00 - America/Belem" value="America/Belem">America/Belem</option>
<option title="UTC-03:00 - America/Cayenne" value="America/Cayenne">America/Cayenne</option>
<option title="UTC-03:00 - America/Fortaleza" value="America/Fortaleza">America/Fortaleza</option>
<option title="UTC-03:00 - America/Maceio" value="America/Maceio">America/Maceio</option>
<option title="UTC-03:00 - America/Miquelon" value="America/Miquelon">America/Miquelon</option>
<option title="UTC-03:00 - America/Montevideo" value="America/Montevideo">America/Montevideo</option>
<option title="UTC-03:00 - America/Nuuk" value="America/Nuuk">America/Nuuk</option>
<option title="UTC-03:00 - America/Paramaribo" value="America/Paramaribo">America/Paramaribo</option>
<option title="UTC-03:00 - America/Punta_Arenas" value="America/Punta_Arenas">America/Punta_Arenas</option>
<option title="UTC-03:00 - America/Recife" value="America/Recife">America/Recife</option>
<option title="UTC-03:00 - America/Santarem" value="America/Santarem">America/Santarem</option>
<option title="UTC-03:00 - America/Santiago" value="America/Santiago">America/Santiago</option>
<option title="UTC-03:00 - America/Sao Paulo" value="America/Sao_Paulo">America/Sao Paulo</option>
<option title="UTC-03:00 - Antarctica/Palmer" value="Antarctica/Palmer">Antarctica/Palmer</option>
<option title="UTC-03:00 - Antarctica/Rothera" value="Antarctica/Rothera">Antarctica/Rothera</option>
<option title="UTC-03:00 - Atlantic/Stanley" value="Atlantic/Stanley">Atlantic/Stanley</option>
</optgroup>
<optgroup label="UTC-02:00 - 27 Nov 2021, 13:20" data-tz-value="UTC-02:00 - America/Noronha - 27 Nov 2021, 13:20">
<option title="UTC-02:00 - America/Noronha" value="America/Noronha">America/Noronha</option>
<option title="UTC-02:00 - Atlantic/South Georgia" value="Atlantic/South_Georgia">Atlantic/South Georgia</option>
</optgroup>
<optgroup label="UTC-01:00 - 27 Nov 2021, 14:20" data-tz-value="UTC-01:00 - America/Scoresbysund - 27 Nov 2021, 14:20">
<option title="UTC-01:00 - America/Scoresbysund" value="America/Scoresbysund">America/Scoresbysund</option>
<option title="UTC-01:00 - Atlantic/Azores" value="Atlantic/Azores">Atlantic/Azores</option>
<option title="UTC-01:00 - Atlantic/Cape Verde" value="Atlantic/Cape_Verde">Atlantic/Cape Verde</option>
</optgroup>
<optgroup label="UTC+00:00 - 27 Nov 2021, 15:20" data-tz-value="UTC+00:00 - UTC - 27 Nov 2021, 15:20">
<option title="UTC+00:00 - UTC" value="UTC" selected="selected">UTC</option>
<option title="UTC+00:00 - Africa/Abidjan" value="Africa/Abidjan">Africa/Abidjan</option>
<option title="UTC+00:00 - Africa/Accra" value="Africa/Accra">Africa/Accra</option>
<option title="UTC+00:00 - Africa/Bamako" value="Africa/Bamako">Africa/Bamako</option>
<option title="UTC+00:00 - Africa/Banjul" value="Africa/Banjul">Africa/Banjul</option>
<option title="UTC+00:00 - Africa/Bissau" value="Africa/Bissau">Africa/Bissau</option>
<option title="UTC+00:00 - Africa/Conakry" value="Africa/Conakry">Africa/Conakry</option>
<option title="UTC+00:00 - Africa/Dakar" value="Africa/Dakar">Africa/Dakar</option>
<option title="UTC+00:00 - Africa/Freetown" value="Africa/Freetown">Africa/Freetown</option>
<option title="UTC+00:00 - Africa/Lome" value="Africa/Lome">Africa/Lome</option>
<option title="UTC+00:00 - Africa/Monrovia" value="Africa/Monrovia">Africa/Monrovia</option>
<option title="UTC+00:00 - Africa/Nouakchott" value="Africa/Nouakchott">Africa/Nouakchott</option>
<option title="UTC+00:00 - Africa/Ouagadougou" value="Africa/Ouagadougou">Africa/Ouagadougou</option>
<option title="UTC+00:00 - Africa/Sao Tome" value="Africa/Sao_Tome">Africa/Sao Tome</option>
<option title="UTC+00:00 - America/Danmarkshavn" value="America/Danmarkshavn">America/Danmarkshavn</option>
<option title="UTC+00:00 - Antarctica/Troll" value="Antarctica/Troll">Antarctica/Troll</option>
<option title="UTC+00:00 - Atlantic/Canary" value="Atlantic/Canary">Atlantic/Canary</option>
<option title="UTC+00:00 - Atlantic/Faroe" value="Atlantic/Faroe">Atlantic/Faroe</option>
<option title="UTC+00:00 - Atlantic/Madeira" value="Atlantic/Madeira">Atlantic/Madeira</option>
<option title="UTC+00:00 - Atlantic/Reykjavik" value="Atlantic/Reykjavik">Atlantic/Reykjavik</option>
<option title="UTC+00:00 - Atlantic/St. Helena" value="Atlantic/St_Helena">Atlantic/St. Helena</option>
<option title="UTC+00:00 - Europe/Dublin" value="Europe/Dublin">Europe/Dublin</option>
<option title="UTC+00:00 - Europe/Guernsey" value="Europe/Guernsey">Europe/Guernsey</option>
<option title="UTC+00:00 - Europe/Isle of Man" value="Europe/Isle_of_Man">Europe/Isle of Man</option>
<option title="UTC+00:00 - Europe/Jersey" value="Europe/Jersey">Europe/Jersey</option>
<option title="UTC+00:00 - Europe/Lisbon" value="Europe/Lisbon">Europe/Lisbon</option>
<option title="UTC+00:00 - Europe/London" value="Europe/London">Europe/London</option>
</optgroup>
<optgroup label="UTC+01:00 - 27 Nov 2021, 16:20" data-tz-value="UTC+01:00 - Africa/Algiers - 27 Nov 2021, 16:20">
<option title="UTC+01:00 - Africa/Algiers" value="Africa/Algiers">Africa/Algiers</option>
<option title="UTC+01:00 - Africa/Bangui" value="Africa/Bangui">Africa/Bangui</option>
<option title="UTC+01:00 - Africa/Brazzaville" value="Africa/Brazzaville">Africa/Brazzaville</option>
<option title="UTC+01:00 - Africa/Casablanca" value="Africa/Casablanca">Africa/Casablanca</option>
<option title="UTC+01:00 - Africa/Ceuta" value="Africa/Ceuta">Africa/Ceuta</option>
<option title="UTC+01:00 - Africa/Douala" value="Africa/Douala">Africa/Douala</option>
<option title="UTC+01:00 - Africa/El Aaiun" value="Africa/El_Aaiun">Africa/El Aaiun</option>
<option title="UTC+01:00 - Africa/Kinshasa" value="Africa/Kinshasa">Africa/Kinshasa</option>
<option title="UTC+01:00 - Africa/Lagos" value="Africa/Lagos">Africa/Lagos</option>
<option title="UTC+01:00 - Africa/Libreville" value="Africa/Libreville">Africa/Libreville</option>
<option title="UTC+01:00 - Africa/Luanda" value="Africa/Luanda">Africa/Luanda</option>
<option title="UTC+01:00 - Africa/Malabo" value="Africa/Malabo">Africa/Malabo</option>
<option title="UTC+01:00 - Africa/Ndjamena" value="Africa/Ndjamena">Africa/Ndjamena</option>
<option title="UTC+01:00 - Africa/Niamey" value="Africa/Niamey">Africa/Niamey</option>
<option title="UTC+01:00 - Africa/Porto-Novo" value="Africa/Porto-Novo">Africa/Porto-Novo</option>
<option title="UTC+01:00 - Africa/Tunis" value="Africa/Tunis">Africa/Tunis</option>
<option title="UTC+01:00 - Arctic/Longyearbyen" value="Arctic/Longyearbyen">Arctic/Longyearbyen</option>
<option title="UTC+01:00 - Europe/Amsterdam" value="Europe/Amsterdam">Europe/Amsterdam</option>
<option title="UTC+01:00 - Europe/Andorra" value="Europe/Andorra">Europe/Andorra</option>
<option title="UTC+01:00 - Europe/Belgrade" value="Europe/Belgrade">Europe/Belgrade</option>
<option title="UTC+01:00 - Europe/Berlin" value="Europe/Berlin">Europe/Berlin</option>
<option title="UTC+01:00 - Europe/Bratislava" value="Europe/Bratislava">Europe/Bratislava</option>
<option title="UTC+01:00 - Europe/Brussels" value="Europe/Brussels">Europe/Brussels</option>
<option title="UTC+01:00 - Europe/Budapest" value="Europe/Budapest">Europe/Budapest</option>
<option title="UTC+01:00 - Europe/Busingen" value="Europe/Busingen">Europe/Busingen</option>
<option title="UTC+01:00 - Europe/Copenhagen" value="Europe/Copenhagen">Europe/Copenhagen</option>
<option title="UTC+01:00 - Europe/Gibraltar" value="Europe/Gibraltar">Europe/Gibraltar</option>
<option title="UTC+01:00 - Europe/Ljubljana" value="Europe/Ljubljana">Europe/Ljubljana</option>
<option title="UTC+01:00 - Europe/Luxembourg" value="Europe/Luxembourg">Europe/Luxembourg</option>
<option title="UTC+01:00 - Europe/Madrid" value="Europe/Madrid">Europe/Madrid</option>
<option title="UTC+01:00 - Europe/Malta" value="Europe/Malta">Europe/Malta</option>
<option title="UTC+01:00 - Europe/Monaco" value="Europe/Monaco">Europe/Monaco</option>
<option title="UTC+01:00 - Europe/Oslo" value="Europe/Oslo">Europe/Oslo</option>
<option title="UTC+01:00 - Europe/Paris" value="Europe/Paris">Europe/Paris</option>
<option title="UTC+01:00 - Europe/Podgorica" value="Europe/Podgorica">Europe/Podgorica</option>
<option title="UTC+01:00 - Europe/Prague" value="Europe/Prague">Europe/Prague</option>
<option title="UTC+01:00 - Europe/Rome" value="Europe/Rome">Europe/Rome</option>
<option title="UTC+01:00 - Europe/San Marino" value="Europe/San_Marino">Europe/San Marino</option>
<option title="UTC+01:00 - Europe/Sarajevo" value="Europe/Sarajevo">Europe/Sarajevo</option>
<option title="UTC+01:00 - Europe/Skopje" value="Europe/Skopje">Europe/Skopje</option>
<option title="UTC+01:00 - Europe/Stockholm" value="Europe/Stockholm">Europe/Stockholm</option>
<option title="UTC+01:00 - Europe/Tirane" value="Europe/Tirane">Europe/Tirane</option>
<option title="UTC+01:00 - Europe/Vaduz" value="Europe/Vaduz">Europe/Vaduz</option>
<option title="UTC+01:00 - Europe/Vatican" value="Europe/Vatican">Europe/Vatican</option>
<option title="UTC+01:00 - Europe/Vienna" value="Europe/Vienna">Europe/Vienna</option>
<option title="UTC+01:00 - Europe/Warsaw" value="Europe/Warsaw">Europe/Warsaw</option>
<option title="UTC+01:00 - Europe/Zagreb" value="Europe/Zagreb">Europe/Zagreb</option>
<option title="UTC+01:00 - Europe/Zurich" value="Europe/Zurich">Europe/Zurich</option>
</optgroup>
<optgroup label="UTC+02:00 - 27 Nov 2021, 17:20" data-tz-value="UTC+02:00 - Africa/Blantyre - 27 Nov 2021, 17:20">
<option title="UTC+02:00 - Africa/Blantyre" value="Africa/Blantyre">Africa/Blantyre</option>
<option title="UTC+02:00 - Africa/Bujumbura" value="Africa/Bujumbura">Africa/Bujumbura</option>
<option title="UTC+02:00 - Africa/Cairo" value="Africa/Cairo">Africa/Cairo</option>
<option title="UTC+02:00 - Africa/Gaborone" value="Africa/Gaborone">Africa/Gaborone</option>
<option title="UTC+02:00 - Africa/Harare" value="Africa/Harare">Africa/Harare</option>
<option title="UTC+02:00 - Africa/Johannesburg" value="Africa/Johannesburg">Africa/Johannesburg</option>
<option title="UTC+02:00 - Africa/Juba" value="Africa/Juba">Africa/Juba</option>
<option title="UTC+02:00 - Africa/Khartoum" value="Africa/Khartoum">Africa/Khartoum</option>
<option title="UTC+02:00 - Africa/Kigali" value="Africa/Kigali">Africa/Kigali</option>
<option title="UTC+02:00 - Africa/Lubumbashi" value="Africa/Lubumbashi">Africa/Lubumbashi</option>
<option title="UTC+02:00 - Africa/Lusaka" value="Africa/Lusaka">Africa/Lusaka</option>
<option title="UTC+02:00 - Africa/Maputo" value="Africa/Maputo">Africa/Maputo</option>
<option title="UTC+02:00 - Africa/Maseru" value="Africa/Maseru">Africa/Maseru</option>
<option title="UTC+02:00 - Africa/Mbabane" value="Africa/Mbabane">Africa/Mbabane</option>
<option title="UTC+02:00 - Africa/Tripoli" value="Africa/Tripoli">Africa/Tripoli</option>
<option title="UTC+02:00 - Africa/Windhoek" value="Africa/Windhoek">Africa/Windhoek</option>
<option title="UTC+02:00 - Asia/Amman" value="Asia/Amman">Asia/Amman</option>
<option title="UTC+02:00 - Asia/Beirut" value="Asia/Beirut">Asia/Beirut</option>
<option title="UTC+02:00 - Asia/Damascus" value="Asia/Damascus">Asia/Damascus</option>
<option title="UTC+02:00 - Asia/Famagusta" value="Asia/Famagusta">Asia/Famagusta</option>
<option title="UTC+02:00 - Asia/Gaza" value="Asia/Gaza">Asia/Gaza</option>
<option title="UTC+02:00 - Asia/Hebron" value="Asia/Hebron">Asia/Hebron</option>
<option title="UTC+02:00 - Asia/Jerusalem" value="Asia/Jerusalem">Asia/Jerusalem</option>
<option title="UTC+02:00 - Asia/Nicosia" value="Asia/Nicosia">Asia/Nicosia</option>
<option title="UTC+02:00 - Europe/Athens" value="Europe/Athens">Europe/Athens</option>
<option title="UTC+02:00 - Europe/Bucharest" value="Europe/Bucharest">Europe/Bucharest</option>
<option title="UTC+02:00 - Europe/Chisinau" value="Europe/Chisinau">Europe/Chisinau</option>
<option title="UTC+02:00 - Europe/Helsinki" value="Europe/Helsinki">Europe/Helsinki</option>
<option title="UTC+02:00 - Europe/Kaliningrad" value="Europe/Kaliningrad">Europe/Kaliningrad</option>
<option title="UTC+02:00 - Europe/Kiev" value="Europe/Kiev">Europe/Kiev</option>
<option title="UTC+02:00 - Europe/Mariehamn" value="Europe/Mariehamn">Europe/Mariehamn</option>
<option title="UTC+02:00 - Europe/Riga" value="Europe/Riga">Europe/Riga</option>
<option title="UTC+02:00 - Europe/Sofia" value="Europe/Sofia">Europe/Sofia</option>
<option title="UTC+02:00 - Europe/Tallinn" value="Europe/Tallinn">Europe/Tallinn</option>
<option title="UTC+02:00 - Europe/Uzhgorod" value="Europe/Uzhgorod">Europe/Uzhgorod</option>
<option title="UTC+02:00 - Europe/Vilnius" value="Europe/Vilnius">Europe/Vilnius</option>
<option title="UTC+02:00 - Europe/Zaporozhye" value="Europe/Zaporozhye">Europe/Zaporozhye</option>
</optgroup>
<optgroup label="UTC+03:00 - 27 Nov 2021, 18:20" data-tz-value="UTC+03:00 - Africa/Addis_Ababa - 27 Nov 2021, 18:20">
<option title="UTC+03:00 - Africa/Addis Ababa" value="Africa/Addis_Ababa">Africa/Addis Ababa</option>
<option title="UTC+03:00 - Africa/Asmara" value="Africa/Asmara">Africa/Asmara</option>
<option title="UTC+03:00 - Africa/Dar es Salaam" value="Africa/Dar_es_Salaam">Africa/Dar es Salaam</option>
<option title="UTC+03:00 - Africa/Djibouti" value="Africa/Djibouti">Africa/Djibouti</option>
<option title="UTC+03:00 - Africa/Kampala" value="Africa/Kampala">Africa/Kampala</option>
<option title="UTC+03:00 - Africa/Mogadishu" value="Africa/Mogadishu">Africa/Mogadishu</option>
<option title="UTC+03:00 - Africa/Nairobi" value="Africa/Nairobi">Africa/Nairobi</option>
<option title="UTC+03:00 - Antarctica/Syowa" value="Antarctica/Syowa">Antarctica/Syowa</option>
<option title="UTC+03:00 - Asia/Aden" value="Asia/Aden">Asia/Aden</option>
<option title="UTC+03:00 - Asia/Baghdad" value="Asia/Baghdad">Asia/Baghdad</option>
<option title="UTC+03:00 - Asia/Bahrain" value="Asia/Bahrain">Asia/Bahrain</option>
<option title="UTC+03:00 - Asia/Kuwait" value="Asia/Kuwait">Asia/Kuwait</option>
<option title="UTC+03:00 - Asia/Qatar" value="Asia/Qatar">Asia/Qatar</option>
<option title="UTC+03:00 - Asia/Riyadh" value="Asia/Riyadh">Asia/Riyadh</option>
<option title="UTC+03:00 - Europe/Istanbul" value="Europe/Istanbul">Europe/Istanbul</option>
<option title="UTC+03:00 - Europe/Kirov" value="Europe/Kirov">Europe/Kirov</option>
<option title="UTC+03:00 - Europe/Minsk" value="Europe/Minsk">Europe/Minsk</option>
<option title="UTC+03:00 - Europe/Moscow" value="Europe/Moscow">Europe/Moscow</option>
<option title="UTC+03:00 - Europe/Simferopol" value="Europe/Simferopol">Europe/Simferopol</option>
<option title="UTC+03:00 - Europe/Volgograd" value="Europe/Volgograd">Europe/Volgograd</option>
<option title="UTC+03:00 - Indian/Antananarivo" value="Indian/Antananarivo">Indian/Antananarivo</option>
<option title="UTC+03:00 - Indian/Comoro" value="Indian/Comoro">Indian/Comoro</option>
<option title="UTC+03:00 - Indian/Mayotte" value="Indian/Mayotte">Indian/Mayotte</option>
</optgroup>
<optgroup label="UTC+03:30 - 27 Nov 2021, 18:50" data-tz-value="UTC+03:30 - Asia/Tehran - 27 Nov 2021, 18:50">
<option title="UTC+03:30 - Asia/Tehran" value="Asia/Tehran">Asia/Tehran</option>
</optgroup>
<optgroup label="UTC+04:00 - 27 Nov 2021, 19:20" data-tz-value="UTC+04:00 - Asia/Baku - 27 Nov 2021, 19:20">
<option title="UTC+04:00 - Asia/Baku" value="Asia/Baku">Asia/Baku</option>
<option title="UTC+04:00 - Asia/Dubai" value="Asia/Dubai">Asia/Dubai</option>
<option title="UTC+04:00 - Asia/Muscat" value="Asia/Muscat">Asia/Muscat</option>
<option title="UTC+04:00 - Asia/Tbilisi" value="Asia/Tbilisi">Asia/Tbilisi</option>
<option title="UTC+04:00 - Asia/Yerevan" value="Asia/Yerevan">Asia/Yerevan</option>
<option title="UTC+04:00 - Europe/Astrakhan" value="Europe/Astrakhan">Europe/Astrakhan</option>
<option title="UTC+04:00 - Europe/Samara" value="Europe/Samara">Europe/Samara</option>
<option title="UTC+04:00 - Europe/Saratov" value="Europe/Saratov">Europe/Saratov</option>
<option title="UTC+04:00 - Europe/Ulyanovsk" value="Europe/Ulyanovsk">Europe/Ulyanovsk</option>
<option title="UTC+04:00 - Indian/Mahe" value="Indian/Mahe">Indian/Mahe</option>
<option title="UTC+04:00 - Indian/Mauritius" value="Indian/Mauritius">Indian/Mauritius</option>
<option title="UTC+04:00 - Indian/Reunion" value="Indian/Reunion">Indian/Reunion</option>
</optgroup>
<optgroup label="UTC+04:30 - 27 Nov 2021, 19:50" data-tz-value="UTC+04:30 - Asia/Kabul - 27 Nov 2021, 19:50">
<option title="UTC+04:30 - Asia/Kabul" value="Asia/Kabul">Asia/Kabul</option>
</optgroup>
<optgroup label="UTC+05:00 - 27 Nov 2021, 20:20" data-tz-value="UTC+05:00 - Antarctica/Mawson - 27 Nov 2021, 20:20">
<option title="UTC+05:00 - Antarctica/Mawson" value="Antarctica/Mawson">Antarctica/Mawson</option>
<option title="UTC+05:00 - Asia/Aqtau" value="Asia/Aqtau">Asia/Aqtau</option>
<option title="UTC+05:00 - Asia/Aqtobe" value="Asia/Aqtobe">Asia/Aqtobe</option>
<option title="UTC+05:00 - Asia/Ashgabat" value="Asia/Ashgabat">Asia/Ashgabat</option>
<option title="UTC+05:00 - Asia/Atyrau" value="Asia/Atyrau">Asia/Atyrau</option>
<option title="UTC+05:00 - Asia/Dushanbe" value="Asia/Dushanbe">Asia/Dushanbe</option>
<option title="UTC+05:00 - Asia/Karachi" value="Asia/Karachi">Asia/Karachi</option>
<option title="UTC+05:00 - Asia/Oral" value="Asia/Oral">Asia/Oral</option>
<option title="UTC+05:00 - Asia/Qyzylorda" value="Asia/Qyzylorda">Asia/Qyzylorda</option>
<option title="UTC+05:00 - Asia/Samarkand" value="Asia/Samarkand">Asia/Samarkand</option>
<option title="UTC+05:00 - Asia/Tashkent" value="Asia/Tashkent">Asia/Tashkent</option>
<option title="UTC+05:00 - Asia/Yekaterinburg" value="Asia/Yekaterinburg">Asia/Yekaterinburg</option>
<option title="UTC+05:00 - Indian/Kerguelen" value="Indian/Kerguelen">Indian/Kerguelen</option>
<option title="UTC+05:00 - Indian/Maldives" value="Indian/Maldives">Indian/Maldives</option>
</optgroup>
<optgroup label="UTC+05:30 - 27 Nov 2021, 20:50" data-tz-value="UTC+05:30 - Asia/Colombo - 27 Nov 2021, 20:50">
<option title="UTC+05:30 - Asia/Colombo" value="Asia/Colombo">Asia/Colombo</option>
<option title="UTC+05:30 - Asia/Kolkata" value="Asia/Kolkata">Asia/Kolkata</option>
</optgroup>
<optgroup label="UTC+05:45 - 27 Nov 2021, 21:05" data-tz-value="UTC+05:45 - Asia/Kathmandu - 27 Nov 2021, 21:05">
<option title="UTC+05:45 - Asia/Kathmandu" value="Asia/Kathmandu">Asia/Kathmandu</option>
</optgroup>
<optgroup label="UTC+06:00 - 27 Nov 2021, 21:20" data-tz-value="UTC+06:00 - Antarctica/Vostok - 27 Nov 2021, 21:20">
<option title="UTC+06:00 - Antarctica/Vostok" value="Antarctica/Vostok">Antarctica/Vostok</option>
<option title="UTC+06:00 - Asia/Almaty" value="Asia/Almaty">Asia/Almaty</option>
<option title="UTC+06:00 - Asia/Bishkek" value="Asia/Bishkek">Asia/Bishkek</option>
<option title="UTC+06:00 - Asia/Dhaka" value="Asia/Dhaka">Asia/Dhaka</option>
<option title="UTC+06:00 - Asia/Omsk" value="Asia/Omsk">Asia/Omsk</option>
<option title="UTC+06:00 - Asia/Qostanay" value="Asia/Qostanay">Asia/Qostanay</option>
<option title="UTC+06:00 - Asia/Thimphu" value="Asia/Thimphu">Asia/Thimphu</option>
<option title="UTC+06:00 - Asia/Urumqi" value="Asia/Urumqi">Asia/Urumqi</option>
<option title="UTC+06:00 - Indian/Chagos" value="Indian/Chagos">Indian/Chagos</option>
</optgroup>
<optgroup label="UTC+06:30 - 27 Nov 2021, 21:50" data-tz-value="UTC+06:30 - Asia/Yangon - 27 Nov 2021, 21:50">
<option title="UTC+06:30 - Asia/Yangon" value="Asia/Yangon">Asia/Yangon</option>
<option title="UTC+06:30 - Indian/Cocos" value="Indian/Cocos">Indian/Cocos</option>
</optgroup>
<optgroup label="UTC+07:00 - 27 Nov 2021, 22:20" data-tz-value="UTC+07:00 - Antarctica/Davis - 27 Nov 2021, 22:20">
<option title="UTC+07:00 - Antarctica/Davis" value="Antarctica/Davis">Antarctica/Davis</option>
<option title="UTC+07:00 - Asia/Bangkok" value="Asia/Bangkok">Asia/Bangkok</option>
<option title="UTC+07:00 - Asia/Barnaul" value="Asia/Barnaul">Asia/Barnaul</option>
<option title="UTC+07:00 - Asia/Ho Chi Minh" value="Asia/Ho_Chi_Minh">Asia/Ho Chi Minh</option>
<option title="UTC+07:00 - Asia/Hovd" value="Asia/Hovd">Asia/Hovd</option>
<option title="UTC+07:00 - Asia/Jakarta" value="Asia/Jakarta">Asia/Jakarta</option>
<option title="UTC+07:00 - Asia/Krasnoyarsk" value="Asia/Krasnoyarsk">Asia/Krasnoyarsk</option>
<option title="UTC+07:00 - Asia/Novokuznetsk" value="Asia/Novokuznetsk">Asia/Novokuznetsk</option>
<option title="UTC+07:00 - Asia/Novosibirsk" value="Asia/Novosibirsk">Asia/Novosibirsk</option>
<option title="UTC+07:00 - Asia/Phnom Penh" value="Asia/Phnom_Penh">Asia/Phnom Penh</option>
<option title="UTC+07:00 - Asia/Pontianak" value="Asia/Pontianak">Asia/Pontianak</option>
<option title="UTC+07:00 - Asia/Tomsk" value="Asia/Tomsk">Asia/Tomsk</option>
<option title="UTC+07:00 - Asia/Vientiane" value="Asia/Vientiane">Asia/Vientiane</option>
<option title="UTC+07:00 - Indian/Christmas" value="Indian/Christmas">Indian/Christmas</option>
</optgroup>
<optgroup label="UTC+08:00 - 27 Nov 2021, 23:20" data-tz-value="UTC+08:00 - Asia/Brunei - 27 Nov 2021, 23:20">
<option title="UTC+08:00 - Asia/Brunei" value="Asia/Brunei">Asia/Brunei</option>
<option title="UTC+08:00 - Asia/Choibalsan" value="Asia/Choibalsan">Asia/Choibalsan</option>
<option title="UTC+08:00 - Asia/Hong Kong" value="Asia/Hong_Kong">Asia/Hong Kong</option>
<option title="UTC+08:00 - Asia/Irkutsk" value="Asia/Irkutsk">Asia/Irkutsk</option>
<option title="UTC+08:00 - Asia/Kuala Lumpur" value="Asia/Kuala_Lumpur">Asia/Kuala Lumpur</option>
<option title="UTC+08:00 - Asia/Kuching" value="Asia/Kuching">Asia/Kuching</option>
<option title="UTC+08:00 - Asia/Macau" value="Asia/Macau">Asia/Macau</option>
<option title="UTC+08:00 - Asia/Makassar" value="Asia/Makassar">Asia/Makassar</option>
<option title="UTC+08:00 - Asia/Manila" value="Asia/Manila">Asia/Manila</option>
<option title="UTC+08:00 - Asia/Shanghai" value="Asia/Shanghai">Asia/Shanghai</option>
<option title="UTC+08:00 - Asia/Singapore" value="Asia/Singapore">Asia/Singapore</option>
<option title="UTC+08:00 - Asia/Taipei" value="Asia/Taipei">Asia/Taipei</option>
<option title="UTC+08:00 - Asia/Ulaanbaatar" value="Asia/Ulaanbaatar">Asia/Ulaanbaatar</option>
<option title="UTC+08:00 - Australia/Perth" value="Australia/Perth">Australia/Perth</option>
</optgroup>
<optgroup label="UTC+08:45 - 28 Nov 2021, 00:05" data-tz-value="UTC+08:45 - Australia/Eucla - 28 Nov 2021, 00:05">
<option title="UTC+08:45 - Australia/Eucla" value="Australia/Eucla">Australia/Eucla</option>
</optgroup>
<optgroup label="UTC+09:00 - 28 Nov 2021, 00:20" data-tz-value="UTC+09:00 - Asia/Chita - 28 Nov 2021, 00:20">
<option title="UTC+09:00 - Asia/Chita" value="Asia/Chita">Asia/Chita</option>
<option title="UTC+09:00 - Asia/Dili" value="Asia/Dili">Asia/Dili</option>
<option title="UTC+09:00 - Asia/Jayapura" value="Asia/Jayapura">Asia/Jayapura</option>
<option title="UTC+09:00 - Asia/Khandyga" value="Asia/Khandyga">Asia/Khandyga</option>
<option title="UTC+09:00 - Asia/Pyongyang" value="Asia/Pyongyang">Asia/Pyongyang</option>
<option title="UTC+09:00 - Asia/Seoul" value="Asia/Seoul">Asia/Seoul</option>
<option title="UTC+09:00 - Asia/Tokyo" value="Asia/Tokyo">Asia/Tokyo</option>
<option title="UTC+09:00 - Asia/Yakutsk" value="Asia/Yakutsk">Asia/Yakutsk</option>
<option title="UTC+09:00 - Pacific/Palau" value="Pacific/Palau">Pacific/Palau</option>
</optgroup>
<optgroup label="UTC+09:30 - 28 Nov 2021, 00:50" data-tz-value="UTC+09:30 - Australia/Darwin - 28 Nov 2021, 00:50">
<option title="UTC+09:30 - Australia/Darwin" value="Australia/Darwin">Australia/Darwin</option>
</optgroup>
<optgroup label="UTC+10:00 - 28 Nov 2021, 01:20" data-tz-value="UTC+10:00 - Antarctica/DumontDUrville - 28 Nov 2021, 01:20">
<option title="UTC+10:00 - Antarctica/DumontDUrville" value="Antarctica/DumontDUrville">Antarctica/DumontDUrville</option>
<option title="UTC+10:00 - Asia/Ust-Nera" value="Asia/Ust-Nera">Asia/Ust-Nera</option>
<option title="UTC+10:00 - Asia/Vladivostok" value="Asia/Vladivostok">Asia/Vladivostok</option>
<option title="UTC+10:00 - Australia/Brisbane" value="Australia/Brisbane">Australia/Brisbane</option>
<option title="UTC+10:00 - Australia/Lindeman" value="Australia/Lindeman">Australia/Lindeman</option>
<option title="UTC+10:00 - Pacific/Chuuk" value="Pacific/Chuuk">Pacific/Chuuk</option>
<option title="UTC+10:00 - Pacific/Guam" value="Pacific/Guam">Pacific/Guam</option>
<option title="UTC+10:00 - Pacific/Port Moresby" value="Pacific/Port_Moresby">Pacific/Port Moresby</option>
<option title="UTC+10:00 - Pacific/Saipan" value="Pacific/Saipan">Pacific/Saipan</option>
</optgroup>
<optgroup label="UTC+10:30 - 28 Nov 2021, 01:50" data-tz-value="UTC+10:30 - Australia/Adelaide - 28 Nov 2021, 01:50">
<option title="UTC+10:30 - Australia/Adelaide" value="Australia/Adelaide">Australia/Adelaide</option>
<option title="UTC+10:30 - Australia/Broken Hill" value="Australia/Broken_Hill">Australia/Broken Hill</option>
</optgroup>
<optgroup label="UTC+11:00 - 28 Nov 2021, 02:20" data-tz-value="UTC+11:00 - Antarctica/Casey - 28 Nov 2021, 02:20">
<option title="UTC+11:00 - Antarctica/Casey" value="Antarctica/Casey">Antarctica/Casey</option>
<option title="UTC+11:00 - Antarctica/Macquarie" value="Antarctica/Macquarie">Antarctica/Macquarie</option>
<option title="UTC+11:00 - Asia/Magadan" value="Asia/Magadan">Asia/Magadan</option>
<option title="UTC+11:00 - Asia/Sakhalin" value="Asia/Sakhalin">Asia/Sakhalin</option>
<option title="UTC+11:00 - Asia/Srednekolymsk" value="Asia/Srednekolymsk">Asia/Srednekolymsk</option>
<option title="UTC+11:00 - Australia/Hobart" value="Australia/Hobart">Australia/Hobart</option>
<option title="UTC+11:00 - Australia/Lord Howe" value="Australia/Lord_Howe">Australia/Lord Howe</option>
<option title="UTC+11:00 - Australia/Melbourne" value="Australia/Melbourne">Australia/Melbourne</option>
<option title="UTC+11:00 - Australia/Sydney" value="Australia/Sydney">Australia/Sydney</option>
<option title="UTC+11:00 - Pacific/Bougainville" value="Pacific/Bougainville">Pacific/Bougainville</option>
<option title="UTC+11:00 - Pacific/Efate" value="Pacific/Efate">Pacific/Efate</option>
<option title="UTC+11:00 - Pacific/Guadalcanal" value="Pacific/Guadalcanal">Pacific/Guadalcanal</option>
<option title="UTC+11:00 - Pacific/Kosrae" value="Pacific/Kosrae">Pacific/Kosrae</option>
<option title="UTC+11:00 - Pacific/Noumea" value="Pacific/Noumea">Pacific/Noumea</option>
<option title="UTC+11:00 - Pacific/Pohnpei" value="Pacific/Pohnpei">Pacific/Pohnpei</option>
</optgroup>
<optgroup label="UTC+12:00 - 28 Nov 2021, 03:20" data-tz-value="UTC+12:00 - Asia/Anadyr - 28 Nov 2021, 03:20">
<option title="UTC+12:00 - Asia/Anadyr" value="Asia/Anadyr">Asia/Anadyr</option>
<option title="UTC+12:00 - Asia/Kamchatka" value="Asia/Kamchatka">Asia/Kamchatka</option>
<option title="UTC+12:00 - Pacific/Fiji" value="Pacific/Fiji">Pacific/Fiji</option>
<option title="UTC+12:00 - Pacific/Funafuti" value="Pacific/Funafuti">Pacific/Funafuti</option>
<option title="UTC+12:00 - Pacific/Kwajalein" value="Pacific/Kwajalein">Pacific/Kwajalein</option>
<option title="UTC+12:00 - Pacific/Majuro" value="Pacific/Majuro">Pacific/Majuro</option>
<option title="UTC+12:00 - Pacific/Nauru" value="Pacific/Nauru">Pacific/Nauru</option>
<option title="UTC+12:00 - Pacific/Norfolk" value="Pacific/Norfolk">Pacific/Norfolk</option>
<option title="UTC+12:00 - Pacific/Tarawa" value="Pacific/Tarawa">Pacific/Tarawa</option>
<option title="UTC+12:00 - Pacific/Wake" value="Pacific/Wake">Pacific/Wake</option>
<option title="UTC+12:00 - Pacific/Wallis" value="Pacific/Wallis">Pacific/Wallis</option>
</optgroup>
<optgroup label="UTC+13:00 - 28 Nov 2021, 04:20" data-tz-value="UTC+13:00 - Antarctica/McMurdo - 28 Nov 2021, 04:20">
<option title="UTC+13:00 - Antarctica/McMurdo" value="Antarctica/McMurdo">Antarctica/McMurdo</option>
<option title="UTC+13:00 - Pacific/Apia" value="Pacific/Apia">Pacific/Apia</option>
<option title="UTC+13:00 - Pacific/Auckland" value="Pacific/Auckland">Pacific/Auckland</option>
<option title="UTC+13:00 - Pacific/Enderbury" value="Pacific/Enderbury">Pacific/Enderbury</option>
<option title="UTC+13:00 - Pacific/Fakaofo" value="Pacific/Fakaofo">Pacific/Fakaofo</option>
<option title="UTC+13:00 - Pacific/Tongatapu" value="Pacific/Tongatapu">Pacific/Tongatapu</option>
</optgroup>
<optgroup label="UTC+13:45 - 28 Nov 2021, 05:05" data-tz-value="UTC+13:45 - Pacific/Chatham - 28 Nov 2021, 05:05">
<option title="UTC+13:45 - Pacific/Chatham" value="Pacific/Chatham">Pacific/Chatham</option>
</optgroup>
<optgroup label="UTC+14:00 - 28 Nov 2021, 05:20" data-tz-value="UTC+14:00 - Pacific/Kiritimati - 28 Nov 2021, 05:20">
<option title="UTC+14:00 - Pacific/Kiritimati" value="Pacific/Kiritimati">Pacific/Kiritimati</option>
</optgroup>
</select>

</dd>
</dl>


</fieldset>
</div>
</div>
<noscript>
<div>Please enable JavaScript in your browser to load the challenge.</div>
</noscript>

<script src="//recaptcha_v2.net/recaptcha_v2/api.js?render=6Le3DVIaAAAAADIZjZzyOPsTB51siWzNIEE5zK4W" async="" defer=""></script>

<input class="g-recaptcha_v2" type="hidden" name="recaptcha_action" value="register" data-recaptcha_v2-v3="6Le3DVIaAAAAADIZjZzyOPsTB51siWzNIEE5zK4W">
<input type="hidden" name="recaptcha_token" value="">


<div class="panel">
<div class="inner">

<fieldset class="submit-buttons">
<input type="hidden" name="agreed" value="true">
<input type="hidden" name="change_lang" value="0">
<input type="hidden" name="confirm_id" value="83872156fef718989e18b4d93e31c994">

<input type="reset" value="Reset" name="reset" class="button2"><input type="submit" tabindex="9" name="submit" id="submit" value="Submit" class="button1 default-submit_action">
<input type="hidden" name="creation_time" value="1638026458">
<input type="hidden" name="form_token" value="ee9e2202968e9299000d5686a813a6fa45d3d1df">

</fieldset>

</div>
</div>
</form>
"""

soup = bs4.BeautifulSoup(form_html, "html.parser")


def test_reg_type():
    form = FormBS(soup.form, Language.get(Path("enfbots_crawler/languages"), "en"))
    assert form.type == FormType.REGISTER


form_2 = """<form class="new_order" id="new_order_card_form" action="/my/orders" accept-charset="UTF-8" method="post" enfbots_crawler-id="crawleruuid-a013c441-d9c7-4e8e-838c-e9d60428ab2b"><input name="utf8" type="hidden" value="✓" id="crawleruuid-6a4684f8-f4d7-4d43-a90d-c443330b8f05" enfbots_crawler-id="crawleruuid-6a4684f8-f4d7-4d43-a90d-c443330b8f05"><input type="hidden" name="authenticity_token" value="6g+GpxGdLMTvBhjukb1Zcr//5RBde9yIvbkQYrrmpOOH2uxuruoZmcYsv7WQu+gGJ/SnmigNg1Rhoxlp9KwLFQ==" id="crawleruuid-4ee411a0-c501-4bda-9feb-6a79aa07d9a3" enfbots_crawler-id="crawleruuid-4ee411a0-c501-4bda-9feb-6a79aa07d9a3"> <input type="hidden" name="this_order" id="this_order" value="a1llSktJTEZ0Sk05UTh6YkVLbG1BVWJuOXhuVGZib1luR3lXWVlSdmEzN25oUE1DQ1ROekN5RW5IaENaTWVFOUNGVG9PVGNFWDNDeVhFUnI5T2Rjbno0NWtJTHNmQXNMUWdhYlUxWGxISUZvZWdBRGZ0dzQwR1R3Tk05S0pORDhzczVzVEo1eHhVU2swNTM4QVRtTytlT2lzQWxUc1hHSXF4eWtETWcxQWpuc1ptdG5XUjBMaTFWdmFEQk9OYmI1Mk14VVJMeCtDa2lZSUpkMHJYSys3eWFoc1RlWE5KN0lHMkZ3SDZKbnlHeU9nYmpNT3BYSHhWaDVIZjFiVWpFYzBGRFVMaVFRbDdOQ3Z6Q09QTDQ3bFZEc1JBSWJOSDU1SVYrc1BXRkp4VlArRzk0bEhsNDl4Y0FMclREaU11ckg5MEZUR0xQMVpoVWRXL1BrWHAzWVFHcGcyRUI2RnhwNkxtOGRZaFZSTUNuMWVKOG9UQWQ3cWtScHhWQWVBNW1sYWRUWGl6OE1FbllKV1dSd25HWmcxa01UYmZPYS9IV2ppM3BpNU9aNnNHbmxuZWZweG5NblNlL3A3LzR0d294TGRFeU9YeEhVWFVoekVDUytKRnQxb2Y5Ni9wWEUxVXRacEV5VVp3WS9FTDUrNWEway9nVEplbWl4UkV5YXBvL0Y0NjNmUDBWNVc4Z05GNE43bWdVQUtOVU1rYmNPcjBTd3ROZDduaDRQMU5uTENwSWNDRFJwNnJCK25XSDhmRFBQVHpwZmJOMnpXVzhOUjI3NVVrNGJMbmU5OE1CTFJOUjVFdE9mc2U3Qy96OEFVTDMyVGxTbzRKNGxqZUxqMkZtb1IxOUE0aURUZEdsV1JmOFB1Um1BUC9maTRvNklmWERFYW5UZDB2YndSZXpjME9tNmlnTXZUY0pGQVZ5eitiUkZJOUlRVGU2emlGYlY0RklCNVFTNlE2M0EyK00wUDlrRVRjR25CUnYzdG5aTTNCMWRwYVV1bmFkblVGWE14UmxkSVdTaHpzV3VCWVU2eFVJU3M3b1pQY3MyWWpTSDMxS2p2T2xFV1NkWk1NS3BkWWp3SzA0ZGFYQjNFSkJSeUI1a3Q3SmJWNWg3dVlwcFA2cDY4MFNMc2lSUWc3TERGVGcxVWxSVVh3WUNmZGR1QzAzeTNFckx0NkdyWXpxWkVLcWYtLUxmU2ZkV2NMcVFFOWRyWTV3aXdUQUE9PQ==--3768e2fd4221a842849caf2079caeebf16e60a4b" enfbots_crawler-id="crawleruuid-1f8a3fee-4609-498c-945d-83ab492069a9"> <input type="hidden" name="payment_method" id="payment_method" value="card" enfbots_crawler-id="crawleruuid-f0a13622-7243-4b57-8905-06650a7e7be5"> <input type="hidden" name="data_descriptor" id="data_descriptor" enfbots_crawler-id="crawleruuid-ed8adfb7-3d69-4095-aeac-635a1e8c4d7a"> <input type="hidden" name="data_value" id="data_value" enfbots_crawler-id="crawleruuid-63c0d0b9-c3ca-49d6-90a3-93b152a8a8f4"> <div class="card mt-2 mb-2"> <div class="card-body"> <input type="hidden" name="payment_style" id="payment_style" value="one" enfbots_crawler-id="crawleruuid-cab08d69-79b4-43c6-b9f9-f9c4f7c1cd9c"> <p class="card-text">We will charge your card $299.95.</p> </div> </div> <fieldset> <legend>Shipping Address</legend> <div class="row"> <div class="col-sm-6"> <div class="form-group"> <label for="subscriber_first_name">First Name</label> <input required="required" class="form-control" maxlength="50" size="50" type="text" value="Tielo Sitz" name="subscriber[first_name]" id="subscriber_first_name" enfbots_crawler-id="crawleruuid-a1b79c36-6d93-4953-b1ec-544e916e0141"> </div> </div> <div class="col-sm-6"> <div class="form-group"> <label for="subscriber_last_name">Last Name</label> <input required="required" class="form-control" maxlength="50" size="50" type="text" value="Tielo Sitz" name="subscriber[last_name]" id="subscriber_last_name" enfbots_crawler-id="crawleruuid-acf0b194-e43a-457a-9a0b-ff29bcf05487"> </div> </div> </div> <div class="row"> <div class="col-sm-6"> <div class="form-group"> <label for="subscriber_address">Address</label> <input required="required" class="form-control" maxlength="100" size="100" type="text" name="subscriber[address]" id="subscriber_address" enfbots_crawler-id="crawleruuid-cd7328bd-ab12-4bf0-8362-92af1bbc8e5d"> </div> </div> <div class="col-sm-6"> <div class="form-group"> <label for="subscriber_address2">Address Line 2</label> <input class="form-control" maxlength="100" size="100" type="text" name="subscriber[address2]" id="subscriber_address2" enfbots_crawler-id="crawleruuid-9faa8739-0c4c-46d9-a5c1-869a28f5eef0"> </div> </div> </div> <div class="row"> <div class="col-sm-4"> <div class="form-group"> <label for="subscriber_city">City</label> <input required="required" class="form-control" maxlength="25" size="25" type="text" name="subscriber[city]" id="subscriber_city" enfbots_crawler-id="crawleruuid-0d0a5149-2221-44b4-be83-92f9ce337743"> </div> </div> <div class="col-sm-4"> <div class="form-group"> <label for="subscriber_state">State/Province</label> <input required="required" class="form-control" maxlength="25" size="25" type="text" name="subscriber[state]" id="subscriber_state" enfbots_crawler-id="crawleruuid-ee5f514c-88e4-4fcd-b53d-5e622244c3c6"> </div> </div> <div class="col-sm-4"> <div class="form-group"> <label for="subscriber_zip">Zip/Postal Code</label> <input required="required" class="form-control" maxlength="16" size="16" type="text" name="subscriber[zip]" id="subscriber_zip" enfbots_crawler-id="crawleruuid-d30f64b1-266a-4258-b11b-fe087509f0f7"> </div> </div> </div> <div class="row"> <div class="col-sm-12"> <div class="form-group"> <label for="subscriber_country">Country</label> <input class="form-control" maxlength="125" size="125" type="text" value="" name="subscriber[country]" id="subscriber_country" enfbots_crawler-id="crawleruuid-c59a16d7-4d76-4f02-84a0-4765e1cf96b5"> </div> </div> </div> <div class="row"> <div class="col-sm-6"> <div class="form-group"> <label for="subscriber_phone">Phone</label> <input required="required" class="form-control" maxlength="20" size="20" type="tel" name="subscriber[phone]" id="subscriber_phone" enfbots_crawler-id="crawleruuid-bd96973d-5af7-402d-9cee-f2aa9d4339ec"> </div> </div> <div class="col-sm-6"> <div class="form-group"> <label for="subscriber_email">Email</label> <input required="required" class="form-control" maxlength="100" size="100" type="email" value="sitzjckbl26d8@infsec-server.inf.ethz.ch" name="subscriber[email]" id="subscriber_email" enfbots_crawler-id="crawleruuid-7282ad3a-7673-4a89-8091-86c548f9d9fd"> </div> </div> </div> </fieldset> <div id="new_card_info" class="card mt-1 mb-1"> <div class="card-body"> <h3><svg class="octicon octicon-lock" viewBox="0 0 12 16" version="1.1" width="12" height="16" aria-hidden="true"><path fill-rule="evenodd" d="M4 13H3v-1h1v1zm8-6v7c0 .55-.45 1-1 1H1c-.55 0-1-.45-1-1V7c0-.55.45-1 1-1h1V4c0-2.2 1.8-4 4-4s4 1.8 4 4v2h1c.55 0 1 .45 1 1zM3.8 6h4.41V4c0-1.22-.98-2.2-2.2-2.2-1.22 0-2.2.98-2.2 2.2v2H3.8zM11 7H2v7h9V7zM4 8H3v1h1V8zm0 2H3v1h1v-1z"></path></svg> Secure credit card payment</h3> <p class="small">Your card information is securely transmitted directly to our processor using SSL encryption and is never sent to our server.</p> <div class="row"> <div class="col-sm-12 col-md-6"> <div class="form-group has-feedback"> <label for="cc-number">Card Number <img style="height: 20px; width: auto;" src="/assets/mc_vs_ax_accpt_h_038_png-714a5570aea08a9146c8edfb88985477a15c56df1c5315fb8acfd7e3f3da43fa.png"></label> <input id="cc-number" type="tel" class="form-control cc-number" autocomplete="cc-number" placeholder="•••• •••• •••• ••••" aria-describedby="cc-number-status" enfbots_crawler-id="crawleruuid-7eb99d8e-a4bd-450b-917a-3d2f72ebadfe"> <span id="cc-number-status" class="sr-only"></span> </div> </div> <div class="col-sm-6 col-md-3"> <div class="form-group has-feedback"> <label for="cc-exp">Expiration</label> <input id="cc-exp" type="tel" class="form-control cc-exp" autocomplete="cc-exp" placeholder="mm/yy" aria-describedby="cc-exp-status" enfbots_crawler-id="crawleruuid-665cd75b-220e-47ae-a572-b817f2a3d3bc"> <span id="cc-number-status" class="sr-only"></span> </div> </div> <div class="col-sm-6 col-md-3"> <div class="form-group has-feedback"> <label for="cc-cvc">Security Code</label> <input id="cc-cvc" type="tel" class="form-control cc-cvc" autocomplete="off" placeholder="•••" aria-describedby="cc-cvc-status" enfbots_crawler-id="crawleruuid-7f237a86-d279-4b4a-a16c-f7ee83f615dd"> <small class="form-text text-muted">3 or 4 digits</small> <span id="cc-number-status" class="sr-only"></span> </div> </div> </div> <div class="row"> <div class="col-sm-12"> <div class="form-check"> <input type="checkbox" name="save_card" id="save_card" value="1" class="form-check-input" enfbots_crawler-id="crawleruuid-11e46f46-dc5b-4995-85aa-854b1af65b4c"> <label class="form-check-label" for="save_card">Store card information</label> </div> <div class="col-sm-12" style="display: none;" id="card-description-area"> <label for="card_description">Card Description</label> <input type="text" name="card_description" id="card_description" value="" maxlength="50" autocomplete="off" class="form-control" enfbots_crawler-id="crawleruuid-16500b66-5850-4a23-ba5c-7031ea6a09dc"> </div> </div> </div> </div> </div> <div class="form-check"> <label class="form-check-label"> <input type="checkbox" name="different_billing_address" id="different_billing_address" value="1" class="billing_address_changer form-check-input" enfbots_crawler-id="crawleruuid-88cad73c-1b8b-4c46-a798-50a7e0ee10fb"> I have a different billing address </label> </div> <fieldset id="billing_addresses" style="display: none;" none;&quot;=""> <legend>Billing Address</legend> <div> <div class="row"> </div> <div class="row"> <div class="col-sm-12"> <label class="btn btn-primary"> <input type="radio" id="new_billing_address" name="billing_address_choice" value="new_address" checked="checked" class="billing_address" enfbots_crawler-id="crawleruuid-227590f8-2413-41f7-ad92-e888e18c3f3f"> Add Billing Address </label> </div> </div> <div id="new_billing_address_fields" style="display: none;"> <div class="row"> <div class="col-sm-6"> <div class="form-group"> <label for="address_first_name">First Name</label> <input autocomplete="off" class="form-control required" maxlength="50" size="50" type="text" name="address[first_name]" id="address_first_name" enfbots_crawler-id="crawleruuid-df91c996-18bc-4f10-970e-4b281d035ad5"> </div> </div> <div class="col-sm-6"> <div class="form-group"> <label for="address_last_name">Last Name</label> <input autocomplete="off" class="form-control required" maxlength="50" size="50" type="text" name="address[last_name]" id="address_last_name" enfbots_crawler-id="crawleruuid-c17a4954-522d-4980-9747-5c2b71b54992"> </div> </div> </div> <div class="row"> <div class="col-sm-6"> <div class="form-group"> <label for="address_address">Address</label> <input autocomplete="off" class="form-control required" maxlength="100" size="100" type="text" name="address[address]" id="address_address" enfbots_crawler-id="crawleruuid-0e09c2d6-463b-4d2c-b33d-95c4b31f9c9d"> </div> </div> <div class="col-sm-6"> <div class="form-group"> <label for="address_address2">Address Line 2</label> <input autocomplete="off" class="form-control" maxlength="100" size="100" type="text" value="" name="address[address2]" id="address_address2" enfbots_crawler-id="crawleruuid-95b057c6-f84e-4f37-867c-18404f5f57aa"> </div> </div> </div> <div class="row"> <div class="col-sm-4"> <div class="form-group"> <label for="address_city">City</label> <input autocomplete="off" class="form-control required" maxlength="25" size="25" type="text" name="address[city]" id="address_city" enfbots_crawler-id="crawleruuid-4a6adac0-55cd-4334-b2fd-a42ef68d6df0"> </div> </div> <div class="col-sm-4"> <div class="form-group"> <label for="address_state">State/Province</label> <input autocomplete="off" class="form-control required" maxlength="25" size="25" type="text" name="address[state]" id="address_state" enfbots_crawler-id="crawleruuid-39cbbef0-3cb6-4e2c-938d-89eca8da8b53"> </div> </div> <div class="col-sm-4"> <div class="form-group"> <label for="address_zip">Zip/Postal Code</label> <input autocomplete="off" class="form-control required" maxlength="16" size="16" type="text" name="address[zip]" id="address_zip" enfbots_crawler-id="crawleruuid-4893336d-3da4-4a3c-b423-abc91840aabb"> </div> </div> </div> <div class="row"> <div class="col-sm-12"> <div class="form-group"> <label for="address_country">Country</label> <input autocomplete="off" class="form-control" maxlength="125" size="125" type="text" value="" name="address[country]" id="address_country" enfbots_crawler-id="crawleruuid-51497dd6-221b-4bb6-b75c-9a544a81e4c4"> </div> </div> </div> <div class="row"> <div class="col-sm-12"> <div class="form-group"> <label for="address_phone">Phone</label> <input autocomplete="off" class="form-control required" maxlength="20" size="20" type="tel" name="address[phone]" id="address_phone" enfbots_crawler-id="crawleruuid-15e6e9fd-0425-4bf7-9294-676aca3e0a3e"> </div> </div> </div> </div> </div> </fieldset> <p> <b>What happens next?</b><br> You will receive a receipt via email. </p> <input type="submit" name="commit" value="Place Order" class="btn btn-primary" data-disable-with="Place Order" id="crawleruuid-424d356f-ba81-4227-98c2-a41ca6f5944e" enfbots_crawler-id="crawleruuid-424d356f-ba81-4227-98c2-a41ca6f5944e"> </form>"""
soup_2 = bs4.BeautifulSoup(form_2, "html.parser")


def test_multistage_form():
    form = FormBS(soup.form, Language.get(Path("enfbots_crawler/languages"), "en"))
    assert form.classify_form(True) == FormType.REGISTER
