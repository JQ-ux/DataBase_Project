// stock/static/js/market-search.js
document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.getElementById('nav-search-input');
    const resultsContainer = document.getElementById('search-results-dropdown');

    if (searchInput) {
        searchInput.addEventListener('input', function() {
            const query = this.value.trim();
            if (query.length < 1) {
                resultsContainer.style.display = 'none';
                return;
            }

            fetch(`/api/search/?q=${encodeURIComponent(query)}`)
                .then(response => response.json())
                .then(data => {
                    resultsContainer.innerHTML = '';
                    if (data.length > 0) {
                        data.forEach(item => {
                            const div = document.createElement('a');
                            div['className'] = 'dropdown-item d-flex justify-content-between align-items-center';
                            div.href = `/stock/${item.symbol}/`;
                            div.innerHTML = `
                                <span><strong>${item.symbol}</strong> - ${item.name}</span>
                                <span class="badge bg-light text-dark">$${item.price}</span>
                            `;
                            resultsContainer.appendChild(div);
                        });
                        resultsContainer.style.display = 'block';
                    } else {
                        resultsContainer.style.display = 'none';
                    }
                });
        });

        // 点击外部隐藏搜索框
        document.addEventListener('click', (e) => {
            if (!searchInput.contains(e.target)) resultsContainer.style.display = 'none';
        });
    }
});