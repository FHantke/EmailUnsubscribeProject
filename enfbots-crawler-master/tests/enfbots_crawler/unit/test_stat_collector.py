from enfbots_crawler.modules.stat_collector import StatCollector


def test_num_searches_preserved() -> None:
    stats = StatCollector()
    stats2 = StatCollector()

    stats.search_performed()
    stats2.search_performed()

    stats.add(stats2)

    assert stats.num_searches == 2
