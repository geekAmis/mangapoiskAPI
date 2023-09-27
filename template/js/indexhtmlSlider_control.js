
    // Первый слайдер
    var mySwiper1 = new Swiper('.swiper-container-big:nth-of-type(1)', {
      slidesPerView: 6,
      spaceBetween: 30,
      pagination: {
        el: '.swiper-container:nth-of-type(1) .swiper-pagination',
        clickable: true,
      },
    });
    // Второй слайдер
    var mySwiper2 = new Swiper('.swiper-container:nth-of-type(1)', {
      slidesPerView: 6,
      spaceBetween: 30,
      pagination: {
        el: '.swiper-container:nth-of-type(1) .swiper-pagination',
        clickable: true,
      },
    });
    // Третий слайдер
    var mySwiper3 = new Swiper('.swiper-container:nth-of-type(2)', {
      slidesPerView: 6,
      spaceBetween: 30,
      pagination: {
        el: '.swiper-container:nth-of-type(2) .swiper-pagination',
        clickable: true,
      },
    });
    // Четвертый слайдер
     var mySwiper4 = new Swiper('.swiper-container:nth-of-type(3)', {
      slidesPerView: 6,
      spaceBetween: 30,
      scrollbar: {
        el: '.swiper-container:nth-of-type(3) .swiper-pagination',
        hide: true,
      },
    });